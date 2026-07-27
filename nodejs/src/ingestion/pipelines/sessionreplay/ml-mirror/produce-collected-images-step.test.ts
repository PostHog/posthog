import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PipelineResultType } from '~/ingestion/framework/results'
import { CollectedImage } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
import { MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { createProduceCollectedImagesStep } from './produce-collected-images-step'

describe('produceCollectedImagesStep', () => {
    let queued: { key: string; value: Buffer }[][]
    let outputs: IngestionOutputs<MlImageScrubOutput>
    let queueMessages: jest.Mock

    beforeEach(() => {
        queued = []
        queueMessages = jest.fn((_output: string, messages: { key: string; value: Buffer }[]) => {
            queued.push(messages)
            return Promise.resolve()
        })
        outputs = { queueMessages } as unknown as IngestionOutputs<MlImageScrubOutput>
    })

    function image(ref: string, byte = 1): CollectedImage {
        return { ref, bytes: Buffer.from([byte]) }
    }

    async function run<T extends { collectedImages?: CollectedImage[] }>(
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

    it('produces each image keyed by its ref as a side effect and strips them from the element', async () => {
        const step = createProduceCollectedImagesStep(outputs)
        const images = [image('image:aa:h1', 1), image('image:aa:h2', 2)]
        const result = await run(step, { collectedImages: images })

        expect(result.value.collectedImages).toBeUndefined()
        expect(queued).toEqual([
            [
                { key: 'image:aa:h1', value: Buffer.from([1]) },
                { key: 'image:aa:h2', value: Buffer.from([2]) },
            ],
        ])
    })

    it('passes through elements with no collected images without producing', async () => {
        const step = createProduceCollectedImagesStep(outputs)
        await run(step, { collectedImages: undefined })
        await run(step, { collectedImages: [] })
        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('dedups refs it already produced across messages', async () => {
        const step = createProduceCollectedImagesStep(outputs)
        await run(step, { collectedImages: [image('image:aa:h1')] })
        await run(step, { collectedImages: [image('image:aa:h1'), image('image:aa:h2')] })
        expect(queued).toEqual([
            [{ key: 'image:aa:h1', value: Buffer.from([1]) }],
            [{ key: 'image:aa:h2', value: Buffer.from([1]) }],
        ])
    })

    it('evicts oldest refs at capacity instead of forgetting the whole working set', async () => {
        const step = createProduceCollectedImagesStep(outputs, 2)
        await run(step, { collectedImages: [image('image:aa:h1'), image('image:aa:h2')] })
        await run(step, { collectedImages: [image('image:aa:h3')] })
        // Only h1 (the oldest) made room for h3; h2 must still dedup — a wholesale clear-on-full
        // would re-produce the entire hot working set every time the cap is hit.
        await run(step, { collectedImages: [image('image:aa:h2'), image('image:aa:h1')] })
        expect(queued.map((batch) => batch.map((m) => m.key))).toEqual([
            ['image:aa:h1', 'image:aa:h2'],
            ['image:aa:h3'],
            ['image:aa:h1'],
        ])
    })

    it('swallows produce failures (a dangling ref reads as a placeholder downstream)', async () => {
        queueMessages.mockRejectedValueOnce(new Error('broker down'))
        const step = createProduceCollectedImagesStep(outputs)
        const result = await run(step, { collectedImages: [image('image:aa:h1')] })
        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('un-marks refs whose produce failed so a recurring image re-produces naturally', async () => {
        queueMessages.mockRejectedValueOnce(new Error('broker down'))
        const step = createProduceCollectedImagesStep(outputs)
        await run(step, { collectedImages: [image('image:aa:h1')] })
        await run(step, { collectedImages: [image('image:aa:h1')] })
        expect(queueMessages).toHaveBeenCalledTimes(2)
        // Once a produce succeeds, the ref dedups again.
        await run(step, { collectedImages: [image('image:aa:h1')] })
        expect(queueMessages).toHaveBeenCalledTimes(2)
    })
})
