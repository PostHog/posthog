import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { prefetchTeamsStep } from '~/ingestion/pipelines/analytics/steps/prefetchTeamsStep'
import { EventHeaders } from '~/types'

type TestInput = { headers: EventHeaders }

function createInput(token: string | undefined): TestInput {
    return { headers: { token } as EventHeaders }
}

describe('prefetchTeamsStep', () => {
    let teamManager: TeamManager

    beforeEach(() => {
        teamManager = { getTeamsByTokens: jest.fn().mockResolvedValue({}) } as unknown as TeamManager
    })

    it('warms the team cache once per distinct token and passes events through', async () => {
        const step = prefetchTeamsStep<TestInput>(teamManager, true)

        const results = await step([
            createInput('token-a'),
            createInput('token-b'),
            createInput('token-a'),
            createInput(undefined),
        ])

        expect(results.map((result) => result.type)).toEqual(Array(4).fill(PipelineResultType.OK))
        expect(results.filter(isOkResult).map((result) => result.value.headers.token)).toEqual([
            'token-a',
            'token-b',
            'token-a',
            undefined,
        ])
        expect(teamManager.getTeamsByTokens).toHaveBeenCalledTimes(1)
        expect(teamManager.getTeamsByTokens).toHaveBeenCalledWith(['token-a', 'token-b'])
    })

    it('passes events through without prefetching when disabled', async () => {
        const step = prefetchTeamsStep<TestInput>(teamManager, false)

        const results = await step([createInput('token-a')])

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(teamManager.getTeamsByTokens).not.toHaveBeenCalled()
    })

    it('keeps events flowing and warns when the warm-up load fails on a retriable error', async () => {
        jest.mocked(teamManager.getTeamsByTokens).mockRejectedValue(
            Object.assign(new Error('postgres down'), { isRetriable: true })
        )
        const step = prefetchTeamsStep<TestInput>(teamManager, true)

        const results = await step([createInput('token-a')])
        await new Promise((resolve) => setImmediate(resolve))

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(logger.warn).toHaveBeenCalledWith(
            '⚠️',
            'prefetchTeams failed on a retriable error',
            expect.objectContaining({ error: expect.stringContaining('postgres down') })
        )
    })
})
