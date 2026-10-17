import { RedisV2 } from '~/common/redis/redis-v2'
import { PostgresRouter } from '~/common/utils/db/postgres'
import * as analytics from '~/common/utils/posthog'
import { Team } from '~/types'

import { WorkflowsExternalDeliveryReporter } from './workflows-external-delivery-reporter'

describe('WorkflowsExternalDeliveryReporter', () => {
    it('bounds pending Redis claims and resumes reporting when they finish', async () => {
        const capture = jest.spyOn(analytics, 'captureTeamEvent').mockImplementation(() => {})
        const claims: (() => void)[] = []
        let ready: () => void = () => {}
        const claimsStarted = new Promise<void>((resolve) => (ready = resolve))
        const redis = {
            useClient: jest.fn(
                () =>
                    new Promise<string>((resolve) => {
                        claims.push(() => resolve('OK'))
                        if (claims.length === 4) {
                            ready()
                        }
                    })
            ),
        } as unknown as RedisV2
        const postgres = {
            query: jest.fn().mockResolvedValue({ rows: [{ email: 'member@example.com' }] }),
        } as unknown as PostgresRouter
        const reporter = new WorkflowsExternalDeliveryReporter(
            { getTeam: (id) => Promise.resolve({ id, organization_id: 'org-id' } as Team) },
            postgres,
            redis
        )
        try {
            const reports = [1, 2, 3, 4].map((id) => reporter.report(id, 'flow-id', ['reader@example.com']))
            await claimsStarted
            const overflow = reporter.report(5, 'flow-id', ['reader@example.com'])
            await overflow
            expect(redis.useClient).toHaveBeenCalledTimes(4)
            for (const claim of claims) {
                claim()
            }
            await Promise.all([...reports, overflow])
            redis.useClient = jest.fn().mockResolvedValue('OK')
            await reporter.report(5, 'flow-id', ['reader@example.com'])
            expect(capture).toHaveBeenCalledTimes(5)
            expect(capture).toHaveBeenLastCalledWith(
                expect.objectContaining({ id: 5 }),
                'workflows message delivered to external recipient',
                { workflow_id: 'flow-id', channel: 'email' }
            )
        } finally {
            capture.mockRestore()
        }
    })
})
