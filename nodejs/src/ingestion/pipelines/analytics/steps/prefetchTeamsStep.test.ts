import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchTeamsStep } from '~/ingestion/pipelines/analytics/steps/prefetchTeamsStep'

type TestInput = { headers: { token?: string } }

function createInput(token?: string): TestInput {
    return { headers: { token } }
}

describe('prefetchTeamsStep', () => {
    it('warms the team cache by header token, skipping events without one', async () => {
        const teamManager = { getTeamsByTokens: jest.fn().mockResolvedValue({}) }
        const step = prefetchTeamsStep<TestInput>(teamManager, true)

        const results = await step([createInput('token-a'), createInput('token-b'), createInput()])

        expect(results.map((result) => result.type)).toEqual(Array(3).fill(PipelineResultType.OK))
        expect(teamManager.getTeamsByTokens).toHaveBeenCalledWith(['token-a', 'token-b'], { flush: true })
    })
})
