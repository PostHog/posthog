import { PostgresRouter } from '~/common/utils/db/postgres'
import { Team } from '~/types'

import { MAX_PENDING_EMAIL_REPORTS, WorkflowsActivationReporter } from './workflows-activation-reporter'

describe('WorkflowsActivationReporter', () => {
    const team = { id: 2, uuid: 'team-uuid', organization_id: 'org-id' } as Team
    const otherTeam = { id: 3, uuid: 'other-team-uuid', organization_id: 'org-id' } as Team
    let getTeam: jest.Mock
    let capture: jest.Mock
    let reporter: WorkflowsActivationReporter
    let unreachablePostgres: PostgresRouter & { query: jest.Mock }

    beforeEach(() => {
        jest.useFakeTimers({ now: new Date('2026-10-03T10:00:00Z') })
        getTeam = jest.fn((teamId: number) => Promise.resolve([team, otherTeam].find((t) => t.id === teamId) ?? null))
        capture = jest.fn()
        unreachablePostgres = {
            query: jest.fn(() => Promise.reject(new Error('connect ECONNREFUSED'))),
        } as unknown as PostgresRouter & { query: jest.Mock }
        reporter = new WorkflowsActivationReporter({ getTeam }, unreachablePostgres, capture)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('captures each team, event and outcome once per hour', async () => {
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
        await reporter.report(2, 'workflows send blocked', {
            reason: 'missing_recipient',
            channel: 'email',
            workflow_id: 'flow-1',
        })
        await reporter.report(2, 'workflows message sent', {
            channel: 'email',
            recipient_outside_org: true,
            workflow_id: 'flow-1',
        })
        await reporter.report(2, 'workflows message sent', {
            recipient_outside_org: true,
            channel: 'email',
            workflow_id: 'flow-2',
        })
        await reporter.report(2, 'workflows message sent', {
            channel: 'email',
            recipient_outside_org: false,
            workflow_id: 'flow-1',
        })
        await reporter.reportPushSent(2, 'flow-1')
        await reporter.reportPushSent(2, 'flow-2')
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
            [team, 'workflows send blocked', { reason: 'missing_recipient', channel: 'email', workflow_id: 'flow-1' }],
            [team, 'workflows message sent', { channel: 'email', recipient_outside_org: true, workflow_id: 'flow-1' }],
            [team, 'workflows message sent', { channel: 'email', recipient_outside_org: false, workflow_id: 'flow-1' }],
            [team, 'workflows message sent', { channel: 'push', recipient_outside_org: true, workflow_id: 'flow-1' }],
            [team, 'workflows send failed', { reason: 'unverified_domain', channel: 'email', workflow_id: 'flow-3' }],
        ])
    })

    it('skips teams it cannot find', async () => {
        await reporter.report(404, 'workflows send blocked', {
            reason: 'quota_limited',
            channel: 'email',
            workflow_id: 'flow-1',
        })

        expect(capture).not.toHaveBeenCalled()
    })

    it('reports no email sent for a minute after the organization members cannot be read', async () => {
        jest.useFakeTimers({ now: new Date('2026-10-03T10:00:00Z'), doNotFake: ['setTimeout', 'clearTimeout'] })
        unreachablePostgres.query
            .mockRejectedValueOnce(new Error('connect ECONNREFUSED'))
            .mockResolvedValue({ rows: [{ organization_id: 'org-id', email: 'member@example.com' }] })

        await reporter.reportEmailSent(2, 'flow-1', ['outsider@example.com'])
        await reporter.reportEmailSent(2, 'flow-2', ['outsider@example.com'])
        jest.setSystemTime(new Date('2026-10-03T10:01:00Z'))
        await reporter.reportEmailSent(2, 'flow-3', ['outsider@example.com'])

        expect(capture.mock.calls).toEqual([
            [team, 'workflows message sent', { channel: 'email', recipient_outside_org: true, workflow_id: 'flow-3' }],
        ])
    })

    it('reports no email sent beyond the pending limit while the organization members load', async () => {
        jest.useRealTimers()
        let releaseMembers: () => void = () => {}
        const members = new Promise((resolve) => {
            releaseMembers = () => resolve({ rows: [{ organization_id: 'org-id', email: 'member@example.com' }] })
        })
        const stalledPostgres = { query: () => members } as unknown as PostgresRouter
        reporter = new WorkflowsActivationReporter({ getTeam }, stalledPostgres, capture)

        const pending = Array.from({ length: MAX_PENDING_EMAIL_REPORTS }, (_, index) =>
            reporter.reportEmailSent(2, `flow-${index}`, ['member@example.com'])
        )
        const overLimit = reporter.reportEmailSent(2, 'flow-over-limit', ['outsider@example.com'])
        releaseMembers()
        await Promise.all([...pending, overLimit])

        expect(capture.mock.calls).toEqual([
            [team, 'workflows message sent', { channel: 'email', recipient_outside_org: false, workflow_id: 'flow-0' }],
        ])
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

        await reporter.report(2, 'workflows send blocked', {
            reason: 'quota_limited',
            channel: 'email',
            workflow_id: 'flow-1',
        })
        await reporter.report(2, 'workflows send blocked', {
            reason: 'quota_limited',
            channel: 'email',
            workflow_id: 'flow-2',
        })

        expect(capture).toHaveBeenLastCalledWith(team, 'workflows send blocked', {
            reason: 'quota_limited',
            channel: 'email',
            workflow_id: 'flow-2',
        })
    })
})
