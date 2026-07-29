import { Message } from 'node-rdkafka'

import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { PipelineResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { isDlqResult, isOkResult } from '~/ingestion/framework/results'
import { withStepRetry } from '~/ingestion/framework/retry'
import { BlobStore, BlobStoreError, EnsureStoredOutcome } from '~/ingestion/pipelines/ai/blob-offload/blob-store'
import { DetectedBlob } from '~/ingestion/pipelines/ai/blob-offload/detect'
import { parseBlobPointer } from '~/ingestion/pipelines/ai/blob-offload/pointer'
import * as aiMetrics from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { Team } from '~/types'

import {
    OffloadAiBlobsConfig,
    WithAiBlobOffloadPlan,
    createExtractAiBlobsStep,
    createUploadAiBlobStep,
    extractAiBlobsFanOut,
    mergeAiBlobPointersFanIn,
} from './offload-ai-blobs-step'

// Inert metric doubles so unit tests can assert what gets recorded; each metric
// shares one inc/observe between direct calls and labels() chains.
jest.mock('~/ingestion/pipelines/ai/metrics', () => {
    const counter = () => {
        const inc = jest.fn()
        return { inc, labels: jest.fn(() => ({ inc })) }
    }
    const histogram = () => {
        const observe = jest.fn()
        return { observe, labels: jest.fn(() => ({ observe })) }
    }
    return {
        aiBlobOffloadEventsCounter: counter(),
        aiBlobOffloadBlobsCounter: counter(),
        aiBlobOffloadBelowFloorCounter: counter(),
        aiBlobOffloadBelowFloorBytes: counter(),
        aiBlobOffloadBlobBytes: histogram(),
        aiBlobOffloadBlobsPerEvent: histogram(),
        aiBlobOffloadEventBytesSaved: histogram(),
        aiBlobOffloadS3Duration: histogram(),
        aiBlobOffloadS3Errors: counter(),
    }
})

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

jest.mock('~/common/utils/posthog', () => ({
    captureException: jest.fn(),
}))

const metricsMock = jest.mocked(aiMetrics)

const PNG_BYTES = Buffer.alloc(20000, 7)
const PNG_B64 = PNG_BYTES.toString('base64')

type ImageParts = { image_url: { url: string } }[]

type Input = { normalizedEvent: PluginEvent; team: Team }

class FakeBlobStore implements BlobStore {
    stored: { teamId: number; hash: string; bytes: Buffer; mime: string }[] = []
    failWith: Error | null = null

    ensureStored(teamId: number, blob: { hash: string; bytes: Buffer; mime: string }): Promise<EnsureStoredOutcome> {
        if (this.failWith) {
            return Promise.reject(this.failWith)
        }
        this.stored.push({ teamId, ...blob })
        return Promise.resolve('uploaded')
    }
}

function makeInput(properties: Record<string, unknown>): Input {
    return {
        normalizedEvent: createTestPluginEvent({ event: '$ai_generation', team_id: 2, properties }),
        team: createTestTeam({ id: 2 }),
    }
}

const CONFIG = {
    isTeamEnabled: (teamId: number): boolean => teamId === 2,
    minBase64Length: 8192,
    maxBlobsPerEvent: 50,
    uploadMaxConcurrency: 8,
}

type OffloadPlan = NonNullable<WithAiBlobOffloadPlan<Input>['aiBlobOffloadPlan']>

const EMPTY_PLAN: OffloadPlan = {
    blobs: [],
    rewrittenProps: {},
    savedChars: 0,
    belowFloorCount: 0,
    belowFloorBytes: 0,
    skipReason: null,
}

function makeBlob(hash: string, mime = 'image/png'): DetectedBlob {
    return { bytes: Buffer.alloc(16, 7), mime, hash, detector: 'data_uri' }
}

/** The same extract → fanOut → via(upload) → fanIn wiring the AI pipeline uses. */
function createOffloadPipeline(store: BlobStore | null, config: OffloadAiBlobsConfig) {
    return newChunkPipelineBuilder<Input, { message: Message }>()
        .sequentially((b) => b.pipe(createExtractAiBlobsStep(store, config)))
        .fanOut(extractAiBlobsFanOut)
        .via((sub) => sub.concurrently((b) => b.pipe(createUploadAiBlobStep(store))))
        .fanIn(mergeAiBlobPointersFanIn)
        .build()
}

async function runOffload(
    store: FakeBlobStore | null,
    config: OffloadAiBlobsConfig,
    input: Input
): Promise<PipelineResultWithContext<Input, { message: Message }>> {
    const pipeline = createOffloadPipeline(store, config)
    pipeline.feed([createOkContext(input, { message: createTestMessage() })])
    const results: PipelineResultWithContext<Input, { message: Message }>[] = []
    let chunk = await pipeline.next()
    while (chunk !== null) {
        results.push(...chunk)
        chunk = await pipeline.next()
    }
    expect(results).toHaveLength(1)
    return results[0]
}

function okEvent(result: PipelineResultWithContext<Input, { message: Message }>): PluginEvent {
    if (!isOkResult(result.result)) {
        throw new Error('expected ok result')
    }
    return result.result.value.normalizedEvent
}

describe('offloadAiBlobs stage', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('offloads binary from heavy props and rewrites them with pointers', async () => {
        const store = new FakeBlobStore()
        const input = makeInput({
            $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }],
            $ai_model: 'gpt-9',
        })
        const result = await runOffload(store, CONFIG, input)
        expect(store.stored).toHaveLength(1)
        expect(store.stored[0].teamId).toBe(2)
        expect(store.stored[0].bytes.equals(PNG_BYTES)).toBe(true)
        const props = okEvent(result).properties!
        const url = (props.$ai_input as ImageParts)[0].image_url.url
        expect(parseBlobPointer(url)?.hash).toBe(store.stored[0].hash)
        expect(props.$ai_model).toBe('gpt-9')
        // original event untouched
        expect((input.normalizedEvent.properties!.$ai_input as ImageParts)[0].image_url.url.startsWith('data:')).toBe(
            true
        )
    })

    it.each([
        [
            'team not enabled',
            new FakeBlobStore(),
            {
                isTeamEnabled: (): boolean => false,
                minBase64Length: 8192,
                maxBlobsPerEvent: 50,
                uploadMaxConcurrency: 8,
            },
        ],
        ['store not configured', null, CONFIG],
    ])('passes through untouched when %s', async (_name, store, config) => {
        const input = makeInput({ $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }] })
        const result = await runOffload(store, config, input)
        expect(okEvent(result)).toBe(input.normalizedEvent)
        if (store) {
            expect(store.stored).toHaveLength(0)
        }
    })

    it('passes through text-only events without touching properties', async () => {
        const store = new FakeBlobStore()
        const input = makeInput({ $ai_input: [{ role: 'user', content: 'just text' }] })
        const result = await runOffload(store, CONFIG, input)
        expect(okEvent(result)).toBe(input.normalizedEvent)
        expect(store.stored).toHaveLength(0)
    })

    it('rejects (leaving the event unmodified) when storage fails', async () => {
        const store = new FakeBlobStore()
        store.failWith = new Error('s3 down')
        const input = makeInput({ $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }] })
        await expect(runOffload(store, CONFIG, input)).rejects.toThrow('s3 down')
        expect((input.normalizedEvent.properties!.$ai_input as ImageParts)[0].image_url.url.startsWith('data:')).toBe(
            true
        )
    })

    it.each([
        ['at the limit', 2, 2],
        ['over the limit', 3, 0],
    ])('enforces the per-event distinct blob limit (%s)', async (_name, blobCount, expectedStored) => {
        const store = new FakeBlobStore()
        const parts = Array.from({ length: blobCount }, (_, i) => ({
            image_url: { url: `data:image/png;base64,${Buffer.alloc(8192, i).toString('base64')}` },
        }))
        const input = makeInput({ $ai_input: parts })
        const result = await runOffload(store, { ...CONFIG, maxBlobsPerEvent: 2 }, input)
        expect(store.stored).toHaveLength(expectedStored)
        if (expectedStored === 0) {
            expect(okEvent(result)).toBe(input.normalizedEvent)
        }
    })

    it('deduplicates identical blobs across multiple heavy props', async () => {
        const store = new FakeBlobStore()
        const imageUrl = `data:image/png;base64,${PNG_B64}`
        const input = makeInput({
            $ai_input: [{ image_url: { url: imageUrl } }],
            $ai_output: [{ image_url: { url: imageUrl } }],
        })
        const result = await runOffload(store, CONFIG, input)
        expect(store.stored).toHaveLength(1)
        const storedHash = store.stored[0].hash
        const props = okEvent(result).properties!
        const inputUrl = (props.$ai_input as ImageParts)[0].image_url.url
        const outputUrl = (props.$ai_output as ImageParts)[0].image_url.url
        expect(parseBlobPointer(inputUrl)?.hash).toBe(storedHash)
        expect(parseBlobPointer(outputUrl)?.hash).toBe(storedHash)
    })

    describe('createExtractAiBlobsStep', () => {
        async function extract(
            store: BlobStore | null,
            config: OffloadAiBlobsConfig,
            properties: Record<string, unknown>
        ): Promise<{ input: Input; value: WithAiBlobOffloadPlan<Input> }> {
            const input = makeInput(properties)
            const result = await createExtractAiBlobsStep(store, config)(input)
            if (!isOkResult(result)) {
                throw new Error('expected ok result')
            }
            return { input, value: result.value }
        }

        it.each([
            ['store not configured', null, CONFIG],
            ['team not enabled', new FakeBlobStore(), { ...CONFIG, isTeamEnabled: (): boolean => false }],
        ])('attaches a null plan (not a skip) when %s', async (_name, store, config) => {
            const { input, value } = await extract(store, config, {
                $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }],
            })
            // Null must not degrade into a skip plan: skip plans record metrics
            // on fan-in, and disabled events must record nothing.
            expect(value.aiBlobOffloadPlan).toBeNull()
            expect(value.normalizedEvent).toBe(input.normalizedEvent)
        })

        it.each([
            ['text-only properties', { $ai_input: [{ role: 'user', content: 'just text' }] }, 0, 0],
            [
                'below-floor payloads',
                {
                    $ai_input: [
                        { image_url: { url: `data:image/png;base64,${Buffer.alloc(600).toString('base64')}` } },
                    ],
                },
                1,
                600,
            ],
        ])('plans a no_blobs skip for %s', async (_name, properties, belowFloorCount, belowFloorBytes) => {
            const { value } = await extract(new FakeBlobStore(), CONFIG, properties)
            expect(value.aiBlobOffloadPlan).toMatchObject({
                skipReason: 'no_blobs',
                blobs: [],
                belowFloorCount,
                belowFloorBytes,
            })
        })

        it('plans a blob_limit_exceeded skip without retaining blob buffers', async () => {
            const properties = {
                $ai_input: Array.from({ length: 2 }, (_, i) => ({
                    image_url: { url: `data:image/png;base64,${Buffer.alloc(8192, i).toString('base64')}` },
                })),
            }
            const { value } = await extract(new FakeBlobStore(), { ...CONFIG, maxBlobsPerEvent: 1 }, properties)
            // blobs must stay empty on this path so the plan doesn't pin large
            // buffers for an event that will never upload them.
            expect(value.aiBlobOffloadPlan).toMatchObject({ skipReason: 'blob_limit_exceeded', blobs: [] })
        })

        it('deduplicates blobs by hash and accounts saved chars across properties', async () => {
            const url = `data:image/png;base64,${PNG_B64}`
            const { value } = await extract(new FakeBlobStore(), CONFIG, {
                $ai_input: [{ image_url: { url } }],
                $ai_output: [{ image_url: { url } }],
            })
            const plan = value.aiBlobOffloadPlan!
            expect(plan.skipReason).toBeNull()
            expect(plan.blobs).toHaveLength(1)
            expect(plan.blobs[0].bytes.equals(PNG_BYTES)).toBe(true)
            const inputPointer = (plan.rewrittenProps.$ai_input as ImageParts)[0].image_url.url
            const outputPointer = (plan.rewrittenProps.$ai_output as ImageParts)[0].image_url.url
            expect(parseBlobPointer(inputPointer)?.hash).toBe(plan.blobs[0].hash)
            expect(outputPointer).toBe(inputPointer)
            // Both occurrences count toward savedChars, dedup notwithstanding.
            expect(plan.savedChars).toBe(2 * (url.length - inputPointer.length))
        })
    })

    describe('extractAiBlobsFanOut', () => {
        it.each([
            ['a null plan', null],
            ["a 'no_blobs' skip", { ...EMPTY_PLAN, skipReason: 'no_blobs' as const }],
            ["a 'blob_limit_exceeded' skip", { ...EMPTY_PLAN, skipReason: 'blob_limit_exceeded' as const }],
        ])('fans out to nothing for %s', (_name, plan) => {
            expect(extractAiBlobsFanOut({ ...makeInput({}), aiBlobOffloadPlan: plan })).toEqual([])
        })

        it('fans out one upload per blob with the owning team id', () => {
            const blobs = [makeBlob('hash-1'), makeBlob('hash-2')]
            const uploads = extractAiBlobsFanOut({ ...makeInput({}), aiBlobOffloadPlan: { ...EMPTY_PLAN, blobs } })
            expect(uploads).toEqual([
                { teamId: 2, blob: blobs[0] },
                { teamId: 2, blob: blobs[1] },
            ])
        })
    })

    describe('createUploadAiBlobStep', () => {
        it('rejects with the wiring-bug error when no store is configured', async () => {
            const step = createUploadAiBlobStep(null)
            await expect(step({ teamId: 2, blob: makeBlob('hash-1') })).rejects.toThrow(
                'AI blob upload step invoked without a configured blob store'
            )
        })

        it('passes the store outcome through in the result value', async () => {
            const blob = makeBlob('hash-1')
            const ensureStored = jest.fn().mockResolvedValue('touched')
            const result = await createUploadAiBlobStep({ ensureStored })({ teamId: 7, blob })
            // The outcome feeds the per-blob metric label on fan-in, so it must
            // survive verbatim, not collapse to 'uploaded'.
            expect(isOkResult(result) && result.value).toEqual({ blob, outcome: 'touched' })
            expect(ensureStored).toHaveBeenCalledWith(7, blob)
        })

        // Production retry options (tries/name), with a 1ms sleep per the
        // retry.test.ts convention so the exhaustion path stays fast.
        describe('under the production retry wrapper', () => {
            const RETRY = { tries: 5, sleepMs: 1, name: 'offload_ai_blobs' }

            it('turns a non-retriable store failure into a dlq sub-result without retrying', async () => {
                const error = new BlobStoreError('blob can never be stored', false)
                const ensureStored = jest.fn().mockRejectedValue(error)
                const step = withStepRetry(createUploadAiBlobStep({ ensureStored }), RETRY)
                const result = await step({ teamId: 2, blob: makeBlob('hash-1') })
                // The DLQ sub-result is what the fan-out stage aggregates into a
                // parent-level DLQ — the consumer must not crash on this path.
                expect(isDlqResult(result)).toBe(true)
                expect(isDlqResult(result) && result.error).toBe(error)
                expect(ensureStored).toHaveBeenCalledTimes(1)
            })

            it('rejects after exhausting retries for a retriable failure', async () => {
                const ensureStored = jest.fn().mockRejectedValue(new BlobStoreError('socket hang up', true))
                const step = withStepRetry(createUploadAiBlobStep({ ensureStored }), RETRY)
                await expect(step({ teamId: 2, blob: makeBlob('hash-1') })).rejects.toThrow('socket hang up')
                expect(ensureStored).toHaveBeenCalledTimes(5)
            })

            it('recovers when a transient failure resolves within the retry budget', async () => {
                const ensureStored = jest
                    .fn()
                    .mockRejectedValueOnce(new BlobStoreError('flaky', true))
                    .mockResolvedValueOnce('uploaded')
                const step = withStepRetry(createUploadAiBlobStep({ ensureStored }), RETRY)
                const result = await step({ teamId: 2, blob: makeBlob('hash-1') })
                expect(isOkResult(result) && result.value.outcome).toBe('uploaded')
                expect(ensureStored).toHaveBeenCalledTimes(2)
            })
        })
    })

    describe('mergeAiBlobPointersFanIn', () => {
        it('strips the plan key and records nothing for a null plan', () => {
            const input = makeInput({ $ai_model: 'gpt-9' })
            const merged = mergeAiBlobPointersFanIn({ ...input, aiBlobOffloadPlan: null }, [])
            expect(merged).toEqual(input)
            expect('aiBlobOffloadPlan' in merged).toBe(false)
            expect(merged.normalizedEvent).toBe(input.normalizedEvent)
            expect(metricsMock.aiBlobOffloadEventsCounter.labels).not.toHaveBeenCalled()
            expect(metricsMock.aiBlobOffloadBelowFloorCounter.inc).not.toHaveBeenCalled()
        })

        it.each([['no_blobs' as const], ['blob_limit_exceeded' as const]])(
            'records the %s skip and its below-floor counts without touching the event',
            (skipReason) => {
                const input = makeInput({ $ai_model: 'gpt-9' })
                const plan = { ...EMPTY_PLAN, skipReason, belowFloorCount: 3, belowFloorBytes: 1200 }
                const merged = mergeAiBlobPointersFanIn({ ...input, aiBlobOffloadPlan: plan }, [])
                expect(merged.normalizedEvent).toBe(input.normalizedEvent)
                expect('aiBlobOffloadPlan' in merged).toBe(false)
                expect(metricsMock.aiBlobOffloadEventsCounter.labels).toHaveBeenCalledWith(skipReason)
                expect(metricsMock.aiBlobOffloadBelowFloorCounter.inc).toHaveBeenCalledWith(3)
                expect(metricsMock.aiBlobOffloadBelowFloorBytes.inc).toHaveBeenCalledWith(1200)
                expect(metricsMock.aiBlobOffloadBlobsPerEvent.observe).not.toHaveBeenCalled()
            }
        )

        it('merges rewritten properties over the event and records offload metrics', () => {
            const imageBlob = makeBlob('hash-1')
            const audioBlob = makeBlob('hash-2', 'audio/mp3')
            const input = makeInput({ $ai_input: [{ image_url: { url: 'data:original' } }], $ai_model: 'gpt-9' })
            const plan = {
                ...EMPTY_PLAN,
                blobs: [imageBlob, audioBlob],
                rewrittenProps: { $ai_input: [{ image_url: { url: 'posthog-blob://rewritten' } }] },
                savedChars: 123,
            }
            const merged = mergeAiBlobPointersFanIn({ ...input, aiBlobOffloadPlan: plan }, [
                { blob: imageBlob, outcome: 'uploaded' },
                { blob: audioBlob, outcome: 'fresh' },
            ])
            expect(merged.normalizedEvent.properties).toEqual({
                $ai_input: [{ image_url: { url: 'posthog-blob://rewritten' } }],
                $ai_model: 'gpt-9',
            })
            expect('aiBlobOffloadPlan' in merged).toBe(false)
            // Original event untouched — the rewrite must not mutate in place.
            expect((input.normalizedEvent.properties!.$ai_input as ImageParts)[0].image_url.url).toBe('data:original')
            expect(metricsMock.aiBlobOffloadBlobsCounter.labels).toHaveBeenCalledWith('data_uri', 'image', 'uploaded')
            expect(metricsMock.aiBlobOffloadBlobsCounter.labels).toHaveBeenCalledWith('data_uri', 'audio', 'fresh')
            expect(metricsMock.aiBlobOffloadBlobBytes.labels).toHaveBeenCalledWith('image')
            expect(metricsMock.aiBlobOffloadBlobBytes.labels).toHaveBeenCalledWith('audio')
            expect(metricsMock.aiBlobOffloadBlobsPerEvent.observe).toHaveBeenCalledWith(2)
            expect(metricsMock.aiBlobOffloadEventBytesSaved.observe).toHaveBeenCalledWith(123)
            expect(metricsMock.aiBlobOffloadEventsCounter.labels).toHaveBeenCalledWith('offloaded')
            expect(metricsMock.aiBlobOffloadBelowFloorCounter.inc).not.toHaveBeenCalled()
        })
    })
})
