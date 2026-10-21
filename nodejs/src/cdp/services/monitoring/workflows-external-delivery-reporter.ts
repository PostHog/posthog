import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import { RedisV2 } from '~/common/redis/redis-v2'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { Team } from '~/types'

const BASE_REDIS_KEY =
    process.env.NODE_ENV === 'test'
        ? '@posthog-test/workflows-external-delivery'
        : '@posthog/workflows-external-delivery'
const MAX_PENDING_REPORTS = 4

export const workflowsExternalDeliveryReportsCounter = new Counter({
    name: 'cdp_workflows_external_delivery_reports_total',
    help: 'Attempts to report a team reaching an external recipient: reported, dropped_busy or failed',
    labelNames: ['outcome'],
})

const mailboxOf = (email: string): string => {
    const [localPart, domain] = email.trim().toLowerCase().split('@')
    return `${localPart.split('+')[0]}@${domain}`
}

export class WorkflowsExternalDeliveryReporter {
    private pendingReports = 0
    private recentlyClaimedTeams = new LRUCache<number, true>({ max: 100_000, ttl: 60_000 })
    private memberMailboxes = new LRUCache<string, Set<string>>({
        maxSize: 50_000,
        sizeCalculation: (mailboxes) => mailboxes.size + 1,
        ttl: 60_000,
        fetchMethod: async (organizationId) => {
            const query = {
                text: 'SELECT u.email FROM posthog_user u JOIN posthog_organizationmembership m ON m.user_id = u.id WHERE m.organization_id = $1',
                query_timeout: 1000,
            }
            const result = await this.postgres.query<{ email: string }>(
                PostgresUse.COMMON_READ,
                query,
                [organizationId],
                'workflowsExternalDeliveryMembers'
            )
            return new Set(result.rows.map(({ email }) => mailboxOf(email)))
        },
    })

    constructor(
        private teamManager: { getTeam(teamId: number): Promise<Team | null> },
        private postgres: PostgresRouter,
        private redis: RedisV2
    ) {}

    public async report(teamId: number, workflowId: string, emailAddresses: string[]): Promise<void> {
        if (this.recentlyClaimedTeams.has(teamId)) {
            return
        }
        if (this.pendingReports >= MAX_PENDING_REPORTS) {
            workflowsExternalDeliveryReportsCounter.inc({ outcome: 'dropped_busy' })
            return
        }
        this.pendingReports++
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (
                !team?.organization_id ||
                !(await this.reachesOutsideOrganization(team.organization_id, emailAddresses))
            ) {
                return
            }
            if (await this.claimReportingHour(teamId)) {
                captureTeamEvent(team, 'workflows message delivered to external recipient', {
                    workflow_id: workflowId,
                    channel: 'email',
                })
                workflowsExternalDeliveryReportsCounter.inc({ outcome: 'reported' })
            }
        } catch (error) {
            workflowsExternalDeliveryReportsCounter.inc({ outcome: 'failed' })
            logger.warn('Failed to report workflows external delivery', { teamId, workflowId, error })
        } finally {
            this.pendingReports--
        }
    }

    private async reachesOutsideOrganization(organizationId: string, emailAddresses: string[]): Promise<boolean> {
        const memberMailboxes = await this.memberMailboxes.fetch(organizationId)
        return !!memberMailboxes && emailAddresses.some((email) => !memberMailboxes.has(mailboxOf(email)))
    }

    private async claimReportingHour(teamId: number): Promise<boolean> {
        const claim = await this.redis.useClient({ name: 'workflowsExternalDelivery' }, (client) =>
            client.set(`${BASE_REDIS_KEY}/${teamId}`, '1', 'EX', 3600, 'NX')
        )
        this.recentlyClaimedTeams.set(teamId, true)
        return claim === 'OK'
    }
}
