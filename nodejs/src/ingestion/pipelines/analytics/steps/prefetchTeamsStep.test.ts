import { TeamManager } from '~/common/utils/team-manager'
import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchTeamsStep } from '~/ingestion/pipelines/analytics/steps/prefetchTeamsStep'
import { EventHeaders } from '~/types'

type TestInput = { headers: EventHeaders }

function createInput(token: string | undefined): TestInput {
    return { headers: { token } as EventHeaders }
}

describe('prefetchTeamsStep', () => {
    it('warms the team cache by header token, skipping events without one', async () => {
        const teamManager = { getTeamsByTokens: jest.fn().mockResolvedValue({}) } as unknown as TeamManager
        const step = prefetchTeamsStep<TestInput>(teamManager, true)

        const results = await step([createInput('token-a'), createInput('token-b'), createInput(undefined)])

        expect(results.map((result) => result.type)).toEqual(Array(3).fill(PipelineResultType.OK))
        expect(teamManager.getTeamsByTokens).toHaveBeenCalledWith(['token-a', 'token-b'], { flush: true })
    })
})
