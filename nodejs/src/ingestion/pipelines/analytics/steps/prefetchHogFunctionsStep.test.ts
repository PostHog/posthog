import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { logger } from '~/common/utils/logger'
import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { prefetchHogFunctionsStep } from '~/ingestion/pipelines/analytics/steps/prefetchHogFunctionsStep'
import { Team } from '~/types'

type TestInput = { team: Team }

function createInput(teamId: number): TestInput {
    return { team: { id: teamId } as unknown as Team }
}

describe('prefetchHogFunctionsStep', () => {
    let hogTransformer: HogTransformer

    beforeEach(() => {
        hogTransformer = {
            prefetchHogFunctionsForTeams: jest.fn().mockResolvedValue(undefined),
        } as unknown as HogTransformer
    })

    it('warms the hog function cache once per distinct team and passes events through', async () => {
        const step = prefetchHogFunctionsStep<TestInput>(hogTransformer, true)

        const results = await step([createInput(3), createInput(4), createInput(3)])

        expect(results.map((result) => result.type)).toEqual(Array(3).fill(PipelineResultType.OK))
        expect(results.filter(isOkResult).map((result) => result.value.team.id)).toEqual([3, 4, 3])
        expect(hogTransformer.prefetchHogFunctionsForTeams).toHaveBeenCalledTimes(1)
        expect(hogTransformer.prefetchHogFunctionsForTeams).toHaveBeenCalledWith([3, 4])
    })

    it('passes events through without prefetching when disabled', async () => {
        const step = prefetchHogFunctionsStep<TestInput>(hogTransformer, false)

        const results = await step([createInput(3)])

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(hogTransformer.prefetchHogFunctionsForTeams).not.toHaveBeenCalled()
    })

    it('keeps events flowing and warns when the warm-up load fails on a retriable error', async () => {
        jest.mocked(hogTransformer.prefetchHogFunctionsForTeams).mockRejectedValue(
            Object.assign(new Error('postgres down'), { isRetriable: true })
        )
        const step = prefetchHogFunctionsStep<TestInput>(hogTransformer, true)

        const results = await step([createInput(3)])
        await new Promise((resolve) => setImmediate(resolve))

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(logger.warn).toHaveBeenCalledWith(
            '⚠️',
            'prefetchHogFunctions failed on a retriable error',
            expect.objectContaining({ error: expect.stringContaining('postgres down') })
        )
    })
})
