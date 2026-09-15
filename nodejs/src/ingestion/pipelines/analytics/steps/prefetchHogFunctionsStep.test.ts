import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchHogFunctionsStep } from '~/ingestion/pipelines/analytics/steps/prefetchHogFunctionsStep'

type TestInput = { team: { id: number } }

function createInput(teamId: number): TestInput {
    return { team: { id: teamId } }
}

describe('prefetchHogFunctionsStep', () => {
    it('warms the hog function cache by team id', async () => {
        const hogTransformer = { prefetchHogFunctionsForTeams: jest.fn().mockResolvedValue(undefined) }
        const step = prefetchHogFunctionsStep<TestInput>(hogTransformer, true)

        const results = await step([createInput(3), createInput(4)])

        expect(results.map((result) => result.type)).toEqual(Array(2).fill(PipelineResultType.OK))
        expect(hogTransformer.prefetchHogFunctionsForTeams).toHaveBeenCalledWith([3, 4])
    })
})
