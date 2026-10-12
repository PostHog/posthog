import { Team } from '~/types'

import { WorkflowsActivationReporter } from './workflows-activation-reporter'

describe('WorkflowsActivationReporter', () => {
    const team = { id: 2, uuid: 'team-uuid', organization_id: 'org-id' } as Team
    const otherTeam = { id: 3, uuid: 'other-team-uuid', organization_id: 'org-id' } as Team
    let getTeam: jest.Mock
    let capture: jest.Mock
    let reporter: WorkflowsActivationReporter

    beforeEach(() => {
        jest.useFakeTimers({ now: new Date('2026-10-03T10:00:00Z') })
        getTeam = jest.fn((teamId: number) => Promise.resolve([team, otherTeam].find((t) => t.id === teamId) ?? null))
        capture = jest.fn()
        reporter = new WorkflowsActivationReporter({ getTeam }, capture)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('captures each team and reason once per hour', async () => {
        await reporter.report(2, 'workflows send failed', {
            reason: 'unverified_domain',
            channel: 'email',
            workflow_id: 'flow-1',
        })
        await reporter.report(2, 'workflows send failed', {
            reason: 'unverified_domain',
            channel: 'email',
            workflow_id: 'flow-2',
        })
        await reporter.report(3, 'workflows send failed', {
            reason: 'unverified_domain',
            channel: 'email',
            workflow_id: 'flow-9',
        })
        await reporter.report(2, 'workflows send failed', {
            reason: 'missing_recipient',
            channel: 'email',
            workflow_id: 'flow-1',
        })
        jest.advanceTimersByTime(60 * 60 * 1000)
        await reporter.report(2, 'workflows send failed', {
            reason: 'unverified_domain',
            channel: 'email',
            workflow_id: 'flow-3',
        })

        expect(capture.mock.calls).toEqual([
            [team, 'workflows send failed', { reason: 'unverified_domain', channel: 'email', workflow_id: 'flow-1' }],
            [
                otherTeam,
                'workflows send failed',
                { reason: 'unverified_domain', channel: 'email', workflow_id: 'flow-9' },
            ],
            [team, 'workflows send failed', { reason: 'missing_recipient', channel: 'email', workflow_id: 'flow-1' }],
            [team, 'workflows send failed', { reason: 'unverified_domain', channel: 'email', workflow_id: 'flow-3' }],
        ])
    })

    it('skips teams it cannot find', async () => {
        await reporter.report(404, 'workflows message delivered', { channel: 'email', workflow_id: 'flow-1' })

        expect(capture).not.toHaveBeenCalled()
    })

    it.each([
        ['a failed team lookup', () => getTeam.mockRejectedValueOnce(new Error('postgres is down'))],
        ['a missing team', () => getTeam.mockResolvedValueOnce(null)],
        [
            'a failed capture',
            () =>
                capture.mockImplementationOnce(() => {
                    throw new Error('capture is down')
                }),
        ],
    ])('reports again after %s', async (_name, failOnce) => {
        failOnce()

        await reporter.report(2, 'workflows message delivered', { channel: 'email', workflow_id: 'flow-1' })
        await reporter.report(2, 'workflows message delivered', { channel: 'email', workflow_id: 'flow-2' })

        expect(capture).toHaveBeenLastCalledWith(team, 'workflows message delivered', {
            channel: 'email',
            workflow_id: 'flow-2',
        })
    })
})
