import { RedisV2 } from '~/common/redis/redis-v2'
import { InternalFetchService } from '~/common/services/internal-fetch'
import { logger } from '~/utils/logger'
import { captureException } from '~/utils/posthog'

// Extensible — add new scopes here with their Django internal endpoint when needed
export type NotificationScope = 'hog_flow'
export type NotificationPriority = 'normal' | 'critical'
export type NotificationTarget = 'owner' | 'team'

export interface NotificationPayload {
    type: string
    teamId: number
    functionId: string
    functionName: string
    createdById: number | null
    priority?: NotificationPriority
    target?: NotificationTarget
}

const SCOPE_URL_MAP: Record<NotificationScope, string> = {
    hog_flow: '/api/projects/{teamId}/internal/hog_flows/notify',
}

const DEBOUNCE_TTL_SECONDS = 86400 // 24 hours
const REDIS_KEY_PREFIX = '@posthog/notification'

/**
 * Sends debounced in-app notifications from Node.js services to Django.
 *
 * Handles Redis-based deduplication (one notification per scope/type/team/function
 * per 24 hours) and fire-and-forget HTTP delivery to the appropriate Django
 * internal endpoint based on scope.
 *
 * Usage:
 *   notificationService.notify('hog_flow', {
 *       type: 'workflow_rate_limited',
 *       teamId: 1,
 *       functionId: 'abc',
 *       functionName: 'My Workflow',
 *       createdById: 42,
 *       priority: 'critical',
 *       target: 'owner',
 *   })
 */
export class NotificationService {
    constructor(
        private redis: RedisV2,
        private internalFetchService: InternalFetchService
    ) {}

    /**
     * Send a debounced notification. At most one notification per
     * (scope, type, teamId, functionId) combination per 24 hours.
     *
     * Never throws and never blocks the caller's critical path.
     */
    async notify(scope: NotificationScope, payload: NotificationPayload): Promise<void> {
        try {
            await this.redis.useClient({ name: 'notification-debounce', failOpen: true }, async (client) => {
                const debounceKey = `${REDIS_KEY_PREFIX}/${scope}/${payload.type}/${payload.teamId}/${payload.functionId}`
                const wasSet = await client.set(debounceKey, '1', 'EX', DEBOUNCE_TTL_SECONDS, 'NX')

                if (wasSet) {
                    const urlTemplate = SCOPE_URL_MAP[scope]
                    const urlPath = urlTemplate.replace('{teamId}', String(payload.teamId))

                    this.internalFetchService
                        .fetch({
                            urlPath: urlPath as `/${string}`,
                            fetchParams: {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    type: payload.type,
                                    hog_flow_id: payload.functionId,
                                    hog_flow_name: payload.functionName,
                                    created_by_id: payload.createdById,
                                    priority: payload.priority ?? 'normal',
                                    target: payload.target ?? 'owner',
                                }),
                            },
                        })
                        .catch((error) => {
                            captureException(error)
                            logger.error('🔴', 'Failed to send notification', {
                                err: error,
                                scope,
                                type: payload.type,
                            })
                        })
                }
            })
        } catch (e) {
            captureException(e)
        }
    }
}
