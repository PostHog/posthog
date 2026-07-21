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
 * - **Non-OK sub-results** (drop/dlq/redirect from a sub step): the parent
 *   adopts the first one; its remaining sub-results still drain and their
 *   side effects and warnings merge into the parent, but values are
 *   discarded. A redirect adopted this way applies to the parent's Kafka
 *   message — sub-elements are not messages.
 * - **Thrown errors** (fan-out, fan-in, or subpipeline) poison the stage
 *   permanently after in-flight work drains, like every other chunk stage.
 *
 * Like processing steps, the fan-out and fan-in functions are passed as named
 * functions so error attribution can name them.
 */
import { Message } from 'node-rdkafka'

import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { dlq, isDlqResult, isOkResult, ok } from '~/ingestion/framework/results'
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
     * When a sub step produces a non-OK result, the whole parent adopts it —
     * a parent either completes fully or fails as one unit. Other parents in
     * the same chunk are unaffected.
     */
    it('fails the whole parent when one of its sub-elements fails', async () => {
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
                    return Promise.resolve(dlq('negative part'))
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
            createOkContext({ id: 'poisoned', parts: [1, -2, 3] }, { message: createTestMessage() }),
            createOkContext({ id: 'healthy', parts: [1, 2] }, { message: createTestMessage() }),
        ])

        const results = []
        let chunk = await pipeline.next()
        while (chunk !== null) {
            results.push(...chunk)
            chunk = await pipeline.next()
        }

        expect(results).toHaveLength(2)
        const failed = results.find((r) => isDlqResult(r.result))!
        expect(failed.result).toMatchObject({ reason: 'negative part' })
        const healthy = results.find((r) => isOkResult(r.result))!
        expect(isOkResult(healthy.result) && healthy.result.value).toEqual({ id: 'healthy', total: 3 })
    })
})
