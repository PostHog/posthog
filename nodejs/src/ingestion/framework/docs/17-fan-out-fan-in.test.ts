/**
 * # Chapter 17: Fan-Out / Fan-In
 *
 * A pipeline step cannot change element cardinality: one element in, one
 * result out. That's the right contract for the pipeline as a whole — every
 * Kafka message must produce exactly one result — but it gets in the way when
 * a single element carries N independent pieces of work (say, an event with
 * several attachments to upload). Without help, the step either processes
 * them sequentially or hand-rolls concurrency inside itself, reinventing the
 * `maxConcurrency` and retry machinery the pipeline already has.
 *
 * The fan-out/fan-in stage contains sub-element cardinality inside itself.
 * It is built in three staged calls — `.fanOut(fn).via(cb).fanIn(fn)` — and
 * the type system enforces the sequence: an unclosed stage exposes nothing
 * but the next call, so only `.fanIn()` yields a buildable pipeline.
 *
 * 1. **`.fanOut(fn)`**: a synchronous function splits each OK element into
 *    sub-elements. Zero sub-elements complete the element immediately.
 * 2. **`.via(cb)`**: the sub-elements flow through a regular chunk
 *    subpipeline — `concurrently` with `maxConcurrency`, per-step `retry`,
 *    `concurrentlyPerGroup`, anything the builder offers. Sub-elements from
 *    different parents share the subpipeline, so one concurrency cap governs
 *    the whole stage.
 * 3. **`.fanIn(fn)`**: when all of a parent's sub-results are in, a
 *    synchronous function folds them back into the parent, which emits as a
 *    single OK result. Cardinality at the parent level is preserved:
 *    N parents in, N results out.
 *
 * ## Semantics
 *
 * - **Ordering**: parents emit as they complete (unordered), like
 *   `concurrentlyPerGroup`.
 * - **Non-OK parents** pass through without fanning out, like `filterMap`.
 * - **Sub-result contract.** OK sub-results are collected for the fan-in.
 *   DROP is the sanctioned way for a sub-step to exclude its sub-element —
 *   silent, the parent fans in with the survivors (consistent with a
 *   zero-fan-out fanning in with `[]`). A DLQ sub-result fails the whole
 *   parent: instead of fanning in, the parent emits a DLQ aggregating its sub
 *   DLQs (count, distinct reasons, every error via AggregateError) once all
 *   siblings have drained — fanning in anyway could emit an element built for
 *   work that never happened, like a pointer to a blob that was never stored.
 *   REDIRECT sub-results are excluded with a warning log: sub-elements are
 *   not Kafka messages, so there is nothing to redirect — route the parent
 *   before fanning out instead. Side effects and warnings from every
 *   sub-result still merge into the parent. Redirects can't escape the stage
 *   (and a DLQ carries no redirect names), so the subpipeline's redirect
 *   names don't propagate to the stage's result type.
 * - **Sub-pipelines are context-agnostic**: the `via` builder's context type
 *   is `FanOutSubContext` — nothing but a public, opaque correlation token
 *   the stage mints per parent (sub steps may see it but can't do anything
 *   with it; unknown tokens fail loudly on fan-in). Context-gated surface
 *   (`teamAware`, `messageAware`, `handleIngestionWarnings`,
 *   `handleResults`) is therefore uncallable inside — sub warnings and side
 *   effects merge into the parent and are handled once by the outer
 *   pipeline. If sub-steps need team or message data, the fan-out function
 *   puts it in the sub-element value.
 * - **Thrown errors** (fan-out, fan-in, or subpipeline) poison the stage
 *   permanently after in-flight work drains, like every other chunk stage.
 *
 * Like processing steps, the fan-out and fan-in functions are passed as named
 * functions so error attribution can name them.
 */
import { Message } from 'node-rdkafka'

import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { drop, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { createTestMessage } from '~/tests/helpers/kafka-message'

describe('Fan-Out / Fan-In', () => {
    /**
     * The motivating shape: an event carries several attachments that must all
     * be uploaded before the event can move on. Fan-out turns the event into
     * one sub-element per attachment, a `concurrently` subpipeline uploads
     * them under one concurrency cap (shared across all events in the chunk),
     * and fan-in rewrites the event with the upload results.
     */
    it('uploads an element’s attachments concurrently and folds the results back in', async () => {
        interface EventWithAttachments {
            eventId: string
            attachments: string[]
        }

        interface PendingUpload {
            eventId: string
            attachment: string
        }

        interface CompletedUpload {
            attachment: string
            url: string
        }

        interface UploadedEvent {
            eventId: string
            urls: string[]
        }

        let inFlight = 0
        let highWater = 0

        // Fan-out and fan-in are named functions, like steps. Both must be
        // synchronous and cheap — the heavy lifting belongs in the subpipeline.
        function attachmentsFanOut(event: EventWithAttachments): PendingUpload[] {
            return event.attachments.map((attachment) => ({ eventId: event.eventId, attachment }))
        }

        function collectUrlsFanIn(event: EventWithAttachments, uploads: CompletedUpload[]): UploadedEvent {
            return { eventId: event.eventId, urls: uploads.map((u) => u.url).sort() }
        }

        // A regular processing step: per-sub retry options would go right here.
        function createUploadStep(): ProcessingStep<PendingUpload, CompletedUpload> {
            return async function uploadStep(upload) {
                inFlight++
                highWater = Math.max(highWater, inFlight)
                await new Promise((resolve) => setImmediate(resolve))
                inFlight--
                return ok({ attachment: upload.attachment, url: `s3://bucket/${upload.attachment}` })
            }
        }

        const pipeline = newChunkPipelineBuilder<EventWithAttachments, { message: Message }>()
            .fanOut(attachmentsFanOut)
            .via((sub) => sub.concurrently((b) => b.pipe(createUploadStep()), { maxConcurrency: 2 }))
            .fanIn(collectUrlsFanIn)
            .build()

        pipeline.feed([
            createOkContext(
                { eventId: 'e1', attachments: ['a.png', 'b.png', 'c.png'] },
                { message: createTestMessage() }
            ),
            // No attachments: completes immediately via fanIn(event, []).
            createOkContext({ eventId: 'e2', attachments: [] }, { message: createTestMessage() }),
        ])

        const collected: UploadedEvent[] = []
        let chunk = await pipeline.next()
        while (chunk !== null) {
            for (const result of chunk) {
                if (isOkResult(result.result)) {
                    collected.push(result.result.value)
                }
            }
            chunk = await pipeline.next()
        }

        // One result per parent, regardless of how many sub-elements each produced.
        expect(collected).toEqual(
            expect.arrayContaining([
                { eventId: 'e1', urls: ['s3://bucket/a.png', 's3://bucket/b.png', 's3://bucket/c.png'] },
                { eventId: 'e2', urls: [] },
            ])
        )
        expect(collected).toHaveLength(2)
        // The cap applied across all sub-elements of all parents.
        expect(highWater).toBeLessThanOrEqual(2)
    })

    /**
     * Retry composes with the stage the same way `maxConcurrency` did above:
     * both are ordinary sub-pipeline knobs, not stage features. Passing
     * `{ retry }` to the per-sub step means a transient failure retries only
     * that sub-element's work — the parent and its sibling sub-elements never
     * notice. Contrast with retrying a monolithic "process everything" parent
     * step, which would redo every sub-element's work on any one failure.
     */
    it('retries a transient sub-step failure without disturbing the parent', async () => {
        interface Job {
            id: string
            parts: number[]
        }

        interface Part {
            parentId: string
            value: number
        }

        let attempts = 0

        function partsFanOut(job: Job): Part[] {
            return job.parts.map((value) => ({ parentId: job.id, value }))
        }

        function sumFanIn(job: Job, parts: Part[]): { id: string; total: number } {
            return { id: job.id, total: parts.reduce((acc, p) => acc + p.value, 0) }
        }

        function createFlakyStep(): ProcessingStep<Part, Part> {
            return function flakyStep(part) {
                attempts++
                if (attempts === 1) {
                    // Retriable errors are retried by the step wrapper; the
                    // stage itself never sees this failure.
                    return Promise.reject(Object.assign(new Error('transient'), { isRetriable: true }))
                }
                return Promise.resolve(ok(part))
            }
        }

        const pipeline = newChunkPipelineBuilder<Job, { message: Message }>()
            .fanOut(partsFanOut)
            .via((sub) => sub.concurrently((b) => b.pipe(createFlakyStep(), { retry: { tries: 3, sleepMs: 1 } })))
            .fanIn(sumFanIn)
            .build()

        pipeline.feed([createOkContext({ id: 'job', parts: [7] }, { message: createTestMessage() })])

        const results = []
        let chunk = await pipeline.next()
        while (chunk !== null) {
            results.push(...chunk)
            chunk = await pipeline.next()
        }

        expect(results).toHaveLength(1)
        expect(isOkResult(results[0].result) && results[0].result.value).toEqual({ id: 'job', total: 7 })
        expect(attempts).toBe(2)
    })

    /**
     * DROP is the sanctioned way for a sub-step to exclude its sub-element:
     * the parent still completes via fan-in, just with the survivors. Use it
     * when a sub-element turns out to need no work — invalid part, cache hit,
     * nothing to upload. (A DLQ sub-result instead fails the whole parent
     * with an aggregated DLQ; REDIRECT is misuse — route the parent before
     * fanning out — and is excluded with a warning log.)
     */
    it('drops a sub-element without failing its parent', async () => {
        interface Item {
            id: string
            parts: number[]
        }

        interface Part {
            parentId: string
            value: number
        }

        function partsFanOut(item: Item): Part[] {
            return item.parts.map((value) => ({ parentId: item.id, value }))
        }

        function sumFanIn(item: Item, parts: Part[]): { id: string; total: number } {
            return { id: item.id, total: parts.reduce((acc, p) => acc + p.value, 0) }
        }

        function createValidatePartStep(): ProcessingStep<Part, Part> {
            return function validatePartStep(part) {
                if (part.value < 0) {
                    // Silently exclude this part; the parent fans in without it.
                    return Promise.resolve(drop('negative part'))
                }
                return Promise.resolve(ok(part))
            }
        }

        const pipeline = newChunkPipelineBuilder<Item, { message: Message }>()
            .fanOut(partsFanOut)
            .via((sub) => sub.concurrently((b) => b.pipe(createValidatePartStep())))
            .fanIn(sumFanIn)
            .build()

        pipeline.feed([
            createOkContext({ id: 'partly-valid', parts: [1, -2, 3] }, { message: createTestMessage() }),
            createOkContext({ id: 'all-valid', parts: [1, 2] }, { message: createTestMessage() }),
        ])

        const collected: { id: string; total: number }[] = []
        let chunk = await pipeline.next()
        while (chunk !== null) {
            for (const result of chunk) {
                if (isOkResult(result.result)) {
                    collected.push(result.result.value)
                }
            }
            chunk = await pipeline.next()
        }

        // Every parent completes OK — the dropped part just contributed nothing.
        expect(collected).toEqual(
            expect.arrayContaining([
                { id: 'partly-valid', total: 4 },
                { id: 'all-valid', total: 3 },
            ])
        )
        expect(collected).toHaveLength(2)
    })
})
