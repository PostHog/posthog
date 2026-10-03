import { Team } from '~/types'

import { WorkflowsActivationReporter } from './workflows-activation-reporter'

describe('WorkflowsActivationReporter', () => {
    const team = { id: 2, uuid: 'team-uuid', organization_id: 'org-id' } as Team
    let capture: jest.Mock
    let reporter: WorkflowsActivationReporter

    beforeEach(() => {
        jest.useFakeTimers({ now: new Date('2026-10-03T10:00:00Z') })
        capture = jest.fn()
        reporter = new WorkflowsActivationReporter(
            { getTeam: (teamId: number) => Promise.resolve(teamId === team.id ? team : null) },
            capture
        )
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('captures each team and reason once per hour', async () => {
        await reporter.report(2, 'workflows send failed', { reason: 'unverified_domain', workflow_id: 'flow-1' })
        await reporter.report(2, 'workflows send failed', { reason: 'unverified_domain', workflow_id: 'flow-2' })
        await reporter.report(2, 'workflows send failed', { reason: 'missing_recipient', workflow_id: 'flow-1' })
        jest.advanceTimersByTime(60 * 60 * 1000)
        await reporter.report(2, 'workflows send failed', { reason: 'unverified_domain', workflow_id: 'flow-3' })

        expect(capture.mock.calls).toEqual([
            [team, 'workflows send failed', { reason: 'unverified_domain', workflow_id: 'flow-1' }],
            [team, 'workflows send failed', { reason: 'missing_recipient', workflow_id: 'flow-1' }],
            [team, 'workflows send failed', { reason: 'unverified_domain', workflow_id: 'flow-3' }],
        ])
    })

    it('skips teams it cannot find', async () => {
        await reporter.report(404, 'workflows message delivered', { channel: 'email', workflow_id: 'flow-1' })

        expect(capture).not.toHaveBeenCalled()
    })
})
