import { logger } from '~/common/utils/logger'
import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { createPrefetchStep } from '~/ingestion/pipelines/analytics/steps/createPrefetchStep'

type TestInput = { key: string | null }

const flushRejections = () => new Promise((resolve) => setImmediate(resolve))

describe('createPrefetchStep', () => {
    let load: jest.Mock<Promise<unknown>, [string[]]>

    const createStep = (enabled = true) =>
        createPrefetchStep<TestInput, string>({
            name: 'prefetchTestStep',
            extractKey: (event) => event.key,
            load,
            enabled,
        })

    beforeEach(() => {
        load = jest.fn().mockResolvedValue({})
    })

    it('stamps the given name on the step for framework attribution', () => {
        expect(createStep().name).toBe('prefetchTestStep')
    })

    it('loads each distinct key once, skips events without a key, and passes every event through', async () => {
        const events: TestInput[] = [{ key: 'a' }, { key: 'b' }, { key: 'a' }, { key: null }]

        const results = await createStep()(events)

        expect(results.map((result) => result.type)).toEqual(Array(4).fill(PipelineResultType.OK))
        expect(results.filter(isOkResult).map((result) => result.value)).toEqual(events)
        expect(load).toHaveBeenCalledTimes(1)
        expect(load).toHaveBeenCalledWith(['a', 'b'])
    })

    it.each([
        ['disabled', false, [{ key: 'a' }]],
        ['no event has a key', true, [{ key: null }]],
        ['the chunk is empty', true, []],
    ])('does not load when %s', async (_case, enabled, events: TestInput[]) => {
        const results = await createStep(enabled)(events)

        expect(results.map((result) => result.type)).toEqual(Array(events.length).fill(PipelineResultType.OK))
        expect(load).not.toHaveBeenCalled()
    })

    it('keeps events flowing and warns when the load fails on a retriable error', async () => {
        load.mockRejectedValue(Object.assign(new Error('postgres down'), { isRetriable: true }))

        const results = await createStep()([{ key: 'a' }])
        await flushRejections()

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(logger.warn).toHaveBeenCalledWith(
            '⚠️',
            'prefetchTestStep failed on a retriable error',
            expect.objectContaining({ error: expect.stringContaining('postgres down') })
        )
    })
})
