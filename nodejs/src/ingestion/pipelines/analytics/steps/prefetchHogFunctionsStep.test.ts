import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchHogFunctionsStep } from '~/ingestion/pipelines/analytics/steps/prefetchHogFunctionsStep'
import { Team } from '~/types'

type TestInput = { team: Team }

function createInput(teamId: number): TestInput {
    return { team: { id: teamId } as unknown as Team }
}

describe('prefetchHogFunctionsStep', () => {
    it('warms the hog function cache by team id', async () => {
        const hogTransformer = {
            prefetchHogFunctionsForTeams: jest.fn().mockResolvedValue(undefined),
        } as unknown as HogTransformer
        const step = prefetchHogFunctionsStep<TestInput>(hogTransformer, true)

        const results = await step([createInput(3), createInput(4)])

        expect(results.map((result) => result.type)).toEqual(Array(2).fill(PipelineResultType.OK))
        expect(hogTransformer.prefetchHogFunctionsForTeams).toHaveBeenCalledWith([3, 4])
    })
})
