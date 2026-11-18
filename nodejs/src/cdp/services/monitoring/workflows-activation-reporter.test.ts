import { FakePostHog, startFakePostHog } from '~/cdp/_tests/fake-posthog'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { Team } from '~/types'

import { WorkflowsActivationReporter } from './workflows-activation-reporter'

describe('WorkflowsActivationReporter', () => {
    const team = { id: 2, uuid: 'team-uuid', organization_id: 'org-id' } as Team
    const otherTeam = { id: 3, uuid: 'other-team-uuid', organization_id: 'org-id' } as Team
    let getTeam: jest.Mock
    let analytics: FakePostHog
    let reporter: WorkflowsActivationReporter
    let unreachablePostgres: PostgresRouter

    const received = async (): Promise<Record<string, unknown>[]> => {
        await analytics.client.flush()
        return analytics.events.map(({ event, properties }) => ({
            event,
            team: properties.team,
            ...Object.fromEntries(
                ['workflow_id', 'channel', 'reason', 'recipient_outside_org']
                    .filter((key) => key in properties)
                    .map((key) => [key, properties[key]])
            ),
        }))
    }
    const sent = (teamUuid: string, workflowId: string, channel: string, recipientOutsideOrg: boolean) => ({
        event: 'workflows message sent',
        team: teamUuid,
        workflow_id: workflowId,
        channel,
        recipient_outside_org: recipientOutsideOrg,
    })

    beforeEach(async () => {
        jest.useFakeTimers({
            now: new Date('2026-10-03T10:00:00Z'),
            doNotFake: [
                'nextTick',
                'queueMicrotask',
                'setImmediate',
                'clearImmediate',
                'setTimeout',
                'clearTimeout',
                'setInterval',
                'clearInterval',
                'hrtime',
                'performance',
            ],
        })
        analytics = await startFakePostHog()
        getTeam = jest.fn((teamId: number) => Promise.resolve([team, otherTeam].find((t) => t.id === teamId) ?? null))
        unreachablePostgres = {
            query: () => Promise.reject(new Error('connect ECONNREFUSED')),
        } as unknown as PostgresRouter
        reporter = new WorkflowsActivationReporter({ getTeam }, unreachablePostgres, analytics.client)
    })

    afterEach(async () => {
        jest.useRealTimers()
        await analytics.close()
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
        jest.setSystemTime(new Date('2026-10-03T11:00:00Z'))
        await reporter.report(2, 'workflows send failed', {
            reason: 'unverified_domain',
            channel: 'email',
            workflow_id: 'flow-3',
        })

        expect(await received()).toEqual([
            {
                event: 'workflows send failed',
                team: 'team-uuid',
                reason: 'unverified_domain',
                channel: 'email',
                workflow_id: 'flow-1',
            },
            {
                event: 'workflows send failed',
                team: 'other-team-uuid',
                reason: 'unverified_domain',
                channel: 'email',
                workflow_id: 'flow-9',
            },
            {
                event: 'workflows send blocked',
                team: 'team-uuid',
                reason: 'missing_recipient',
                channel: 'email',
                workflow_id: 'flow-1',
            },
            sent('team-uuid', 'flow-1', 'email', true),
            sent('team-uuid', 'flow-1', 'email', false),
            sent('team-uuid', 'flow-1', 'push', true),
            {
                event: 'workflows send failed',
                team: 'team-uuid',
                reason: 'unverified_domain',
                channel: 'email',
                workflow_id: 'flow-3',
            },
        ])
    })

    it('skips teams it cannot find', async () => {
        await reporter.report(404, 'workflows send blocked', {
            reason: 'quota_limited',
            channel: 'email',
            workflow_id: 'flow-1',
        })

        expect(await received()).toEqual([])
    })

    it.each([
        ['a failed team lookup', () => getTeam.mockRejectedValueOnce(new Error('postgres is down'))],
        ['a missing team', () => getTeam.mockResolvedValueOnce(null)],
        [
            'a failed capture',
            () =>
                jest.spyOn(analytics.client, 'capture').mockImplementationOnce(() => {
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

        expect(await received()).toEqual([
            {
                event: 'workflows send blocked',
                team: 'team-uuid',
                reason: 'quota_limited',
                channel: 'email',
                workflow_id: 'flow-2',
            },
        ])
    })
})
