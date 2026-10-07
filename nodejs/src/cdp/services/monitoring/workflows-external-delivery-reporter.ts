import { LRUCache } from 'lru-cache'
import { randomUUID } from 'node:crypto'

import { RedisV2 } from '~/common/redis/redis-v2'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { Team } from '~/types'

export class WorkflowsExternalDeliveryReporter {
    private members = new LRUCache<string, Set<string>>({
        maxSize: 50_000,
        sizeCalculation: (members) => members.size + 1,
        ttl: 60_000,
        fetchMethod: async (organizationId) => {
            const query = {
                text: 'SELECT u.email FROM posthog_user u JOIN posthog_organizationmembership m ON m.user_id = u.id WHERE m.organization_id = $1',
                query_timeout: 1000,
            }
            const result = await this.postgres.query<{ email: string }>(
                PostgresUse.COMMON_WRITE,
                query,
                [organizationId],
                'workflowActivationMembers'
            )
            return new Set(result.rows.map(({ email }) => email.trim().toLowerCase()))
        },
    })

    constructor(
        private teamManager: { getTeam(teamId: number): Promise<Team | null> },
        private postgres: PostgresRouter,
        private redis: RedisV2
    ) {}

    public async report(teamId: number, workflowId: string, emailAddresses: string[]): Promise<void> {
        const key = `workflows:external-delivery:${teamId}`
        const token = randomUUID()
        let claimed = false
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team || !team.organization_id || emailAddresses.length === 0) {
                return
            }
            const members = await this.members.fetch(team.organization_id)
            if (!members || !emailAddresses.some((email) => !members.has(email.trim().toLowerCase()))) {
                return
            }
            claimed =
                (await this.redis.useClient({ name: 'workflowsExternalDelivery' }, (client) =>
                    client.set(key, token, 'EX', 3600, 'NX')
                )) === 'OK'
            if (!claimed) {
                return
            }
            captureTeamEvent(team, 'workflows message delivered to external recipient', {
                workflow_id: workflowId,
                channel: 'email',
            })
        } catch (error) {
            logger.warn('Failed to report workflows external delivery', { teamId, workflowId, error })
            if (claimed) {
                await this.redis.useClient({ name: 'workflowsExternalDeliveryRelease', failOpen: true }, (client) =>
                    client.eval(
                        "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0",
                        1,
                        key,
                        token
                    )
                )
            }
        }
    }
}
