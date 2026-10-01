import { CollectedImageBatch } from '@posthog/replay-anonymizer'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PipelineResultType } from '~/ingestion/framework/results'
import { CAPTURE_TIMESTAMP_HEADER } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'
import { MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { MlMirrorMetrics } from './metrics'
import { createProduceCollectedImagesStep } from './produce-collected-images-step'
import { ProducedImageRefs } from './produced-refs'

describe('produceCollectedImagesStep', () => {
    const CAPTURED_AT = 1_700_000_000_000
    let queued: { key: string; value: Buffer; headers?: Record<string, string> }[][]
    let outputs: IngestionOutputs<MlImageScrubOutput>
    let queueMessages: jest.Mock

    beforeEach(() => {
        queued = []
        queueMessages = jest.fn(
            (_output: string, messages: { key: string; value: Buffer; headers?: Record<string, string> }[]) => {
                queued.push(messages)
                return Promise.resolve()
            }
        )
        outputs = { queueMessages } as unknown as IngestionOutputs<MlImageScrubOutput>
    })

    function createStep(producedRefCacheMax = 500_000) {
        return createProduceCollectedImagesStep(outputs, new ProducedImageRefs(producedRefCacheMax))
    }

    function images(namespace: string, hashes: string[], byte = 1): CollectedImageBatch {
        return CollectedImageBatch.fromImages(
            namespace,
            hashes.map((hash, index) => ({ hash, bytes: Buffer.from([byte + index]) }))
        )!
    }

    async function run<T extends { collectedImages?: CollectedImageBatch; message: { timestamp?: number } }>(
        step: ReturnType<typeof createProduceCollectedImagesStep<T>>,
        input: T
    ) {
        const result = await step(input)
        if (result.type !== PipelineResultType.OK) {
            throw new Error(`expected ok, got ${result.type}`)
        }
        await Promise.all(result.sideEffects)
        return result
    }

    function v3SessionInput(sessionId: string, collectedImages: CollectedImageBatch) {
        const key = {
            identity: { teamId: 42, sessionId, sessionMonth: '2026-09' },
            plaintext: Buffer.alloc(32),
            wrapped: Buffer.alloc(0),
        }
        return {
            message: { timestamp: CAPTURED_AT },
            headers: { session_id: sessionId },
            mlKeys: { session: key, image: key },
            collectedImages,
        }
    }

    it('produces each image keyed by its ref as a side effect and strips them from the element', async () => {
        const step = createStep()
        const result = await run(step, {
            collectedImages: images('aa', ['h1', 'h2']),
            message: { timestamp: CAPTURED_AT },
        })

        expect(result.value.collectedImages).toBeUndefined()
        expect(queued).toEqual([
            [
                {
                    key: 'image:aa:h1',
                    value: Buffer.from([1]),
                    headers: { [CAPTURE_TIMESTAMP_HEADER]: String(CAPTURED_AT), ai_research_ingestion_version: '1' },
                },
                {
                    key: 'image:aa:h2',
                    value: Buffer.from([2]),
                    headers: { [CAPTURE_TIMESTAMP_HEADER]: String(CAPTURED_AT), ai_research_ingestion_version: '1' },
                },
            ],
        ])
    })

    it('passes through elements with no collected images without producing', async () => {
        const step = createStep()
        await run(step, { collectedImages: undefined, message: { timestamp: CAPTURED_AT } })
        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('dedups refs it already produced across messages', async () => {
        const step = createStep()
        await run(step, { collectedImages: images('aa', ['h1']), message: { timestamp: CAPTURED_AT } })
        await run(step, { collectedImages: images('aa', ['h1', 'h2']), message: { timestamp: CAPTURED_AT } })
        expect(queued).toEqual([
            [
                {
                    key: 'image:aa:h1',
                    value: Buffer.from([1]),
                    headers: { [CAPTURE_TIMESTAMP_HEADER]: String(CAPTURED_AT), ai_research_ingestion_version: '1' },
                },
            ],
            [
                {
                    key: 'image:aa:h2',
                    value: Buffer.from([2]),
                    headers: { [CAPTURE_TIMESTAMP_HEADER]: String(CAPTURED_AT), ai_research_ingestion_version: '1' },
                },
            ],
        ])
    })

    it('dedups a ref that another session of the team produced', async () => {
        const step = createStep()
        const hash = 'h1'.padEnd(22, 'x')

        await run(step, v3SessionInput('01a0c669-8800-7000-8000-000000000001', images('v3:42:2026-09', [hash])))
        await run(step, v3SessionInput('01a0c669-8800-7000-8000-000000000002', images('v3:42:2026-09', [hash])))

        expect(queued).toHaveLength(1)
    })

    it('refuses to produce images whose refs name another team', async () => {
        const step = createStep()
        const input = v3SessionInput(
            '01a0c669-8800-7000-8000-000000000001',
            images('v3:43:2026-09', ['h1'.padEnd(22, 'x')])
        )

        await expect(Promise.resolve().then(() => step(input))).rejects.toThrow('ownership mismatch')
        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('evicts oldest refs at capacity instead of forgetting the whole working set', async () => {
        const step = createStep(2)
        await run(step, { collectedImages: images('aa', ['h1', 'h2']), message: { timestamp: CAPTURED_AT } })
        await run(step, { collectedImages: images('aa', ['h3']), message: { timestamp: CAPTURED_AT } })
        // Only h1 (the oldest) made room for h3; h2 must still dedup — a wholesale clear-on-full
        // would re-produce the entire hot working set every time the cap is hit.
        await run(step, { collectedImages: images('aa', ['h2', 'h1']), message: { timestamp: CAPTURED_AT } })
        expect(queued.map((batch) => batch.map((m) => m.key))).toEqual([
            ['image:aa:h1', 'image:aa:h2'],
            ['image:aa:h3'],
            ['image:aa:h1'],
        ])
    })

    it('swallows produce failures (a dangling ref reads as a placeholder downstream)', async () => {
        queueMessages.mockRejectedValueOnce(new Error('broker down'))
        const step = createStep()
        const result = await run(step, { collectedImages: images('aa', ['h1']), message: { timestamp: CAPTURED_AT } })
        expect(result.type).toBe(PipelineResultType.OK)
    })

    it.each([
        ['delivered', false, 1],
        ['failed', true, 0],
    ])('counts the wire version of a %s produce', async (_outcome, rejects, expected) => {
        if (rejects) {
            queueMessages.mockRejectedValueOnce(new Error('broker down'))
        }
        const incrementVersion = jest.spyOn(MlMirrorMetrics, 'incrementMlProducedVersion')
        try {
            const step = createStep()
            await run(step, { collectedImages: images('aa', ['h1']), message: { timestamp: CAPTURED_AT } })
            expect(incrementVersion).toHaveBeenCalledTimes(expected)
        } finally {
            incrementVersion.mockRestore()
        }
    })

    it('un-marks refs whose produce failed so a recurring image re-produces naturally', async () => {
        queueMessages.mockRejectedValueOnce(new Error('broker down'))
        const step = createStep()
        await run(step, { collectedImages: images('aa', ['h1']), message: { timestamp: CAPTURED_AT } })
        await run(step, { collectedImages: images('aa', ['h1']), message: { timestamp: CAPTURED_AT } })
        expect(queueMessages).toHaveBeenCalledTimes(2)
        // Once a produce succeeds, the ref dedups again.
        await run(step, { collectedImages: images('aa', ['h1']), message: { timestamp: CAPTURED_AT } })
        expect(queueMessages).toHaveBeenCalledTimes(2)
    })
})
