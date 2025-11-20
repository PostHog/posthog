import Redis from 'ioredis'
import { Consumer, EachBatchPayload } from 'kafkajs'

import {
    KAFKA_NOTIFICATION_EVENTS,
    KAFKA_NOTIFICATION_USER_DISPATCH,
    prefix as KAFKA_PREFIX,
} from '../../config/kafka-topics'
import {
    HealthCheckResult,
    HealthCheckResultDegraded,
    HealthCheckResultError,
    HealthCheckResultOk,
    Hub,
    PluginServerService,
} from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { logger } from '../../utils/logger'
import { setupEventHandlers } from './kafka-queue'

interface GenericNotificationEvent {
    event_id: string
    timestamp: string
    team_id: number
    resource_type: string
    event_type: string
    resource_id: string | null
    title: string
    message: string
    context: Record<string, any>
    priority: string
}

interface UserPreferences {
    [resourceType: string]: boolean
}

export const startNotificationPreferenceFilterConsumer = async (hub: Hub): Promise<PluginServerService> => {
    logger.info('🔔', 'Starting notification preference filter consumer (Stage 2)')

    const { kafka, postgres } = hub
    const redis = new Redis(process.env.NOTIFICATIONS_REDIS_URL || process.env.REDIS_URL || 'redis://localhost:6379')

    let inflightBatch: Promise<void> | null = null

    const consumer = kafka.consumer({
        groupId: `${KAFKA_PREFIX}notification-preference-filter`,
        sessionTimeout: hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
        rebalanceTimeout: hub.KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS ?? undefined,
        readUncommitted: false,
    })
    setupEventHandlers(consumer)

    await consumer.subscribe({ topic: KAFKA_NOTIFICATION_EVENTS, fromBeginning: false })
    await consumer.run({
        eachBatch: async (payload) => {
            inflightBatch = eachBatchPreferenceFilter(payload, postgres, redis, hub.kafkaProducer)
            await inflightBatch
            inflightBatch = null
        },
    })

    const onShutdown = async () => {
        try {
            await consumer.stop()
        } catch (e) {
            logger.error('🚨', 'Error stopping preference filter consumer', e)
        }
        if (inflightBatch) {
            logger.info('🔔', 'Waiting for in-flight preference filter batch to complete...')
            await inflightBatch
        }
        try {
            await consumer.disconnect()
        } catch (e) {
            logger.error('🚨', 'Error disconnecting preference filter consumer', e)
        }
        try {
            await redis.quit()
        } catch (e) {
            logger.error('🚨', 'Error disconnecting Redis', e)
        }
    }

    return {
        id: 'notification-preference-filter',
        healthcheck: makeHealthCheck(consumer, hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS),
        onShutdown,
    }
}

async function eachBatchPreferenceFilter(
    { batch, heartbeat }: EachBatchPayload,
    postgres: PostgresRouter,
    redis: Redis,
    kafkaProducer: any
): Promise<void> {
    const startTime = Date.now()
    let totalUserDispatches = 0

    for (const message of batch.messages) {
        if (!message.value) {
            continue
        }

        try {
            const event: GenericNotificationEvent = JSON.parse(message.value.toString())

            // Get all users in the team
            const teamUsersResult = await postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT DISTINCT user_id FROM posthog_organizationmembership om
                JOIN posthog_team t ON t.organization_id = om.organization_id
                WHERE t.id = $1`,
                [event.team_id],
                'getTeamUsers'
            )

            const teamUserIds = teamUsersResult.rows.map((row) => row.user_id)

            logger.debug('🔔', 'Processing notification event', {
                event_id: event.event_id,
                team_id: event.team_id,
                resource_type: event.resource_type,
                team_users: teamUserIds.length,
            })

            // For each user, check preferences and fan-out
            for (const userId of teamUserIds) {
                const shouldNotify = await checkUserPreference(
                    userId,
                    event.team_id,
                    event.resource_type,
                    redis,
                    postgres
                )

                if (shouldNotify) {
                    // Produce user-specific dispatch event
                    await kafkaProducer.produce({
                        topic: KAFKA_NOTIFICATION_USER_DISPATCH,
                        key: Buffer.from(`user:${userId}`),
                        value: Buffer.from(
                            JSON.stringify({
                                user_id: userId,
                                team_id: event.team_id,
                                resource_type: event.resource_type,
                                event_type: event.event_type,
                                resource_id: event.resource_id,
                                title: event.title,
                                message: event.message,
                                context: event.context,
                                priority: event.priority,
                                original_event_id: event.event_id,
                            })
                        ),
                    })

                    totalUserDispatches++
                }
            }

            logger.debug('🔔', 'Notification fan-out complete', {
                event_id: event.event_id,
                team_users: teamUserIds.length,
                dispatched: totalUserDispatches,
            })
        } catch (error) {
            logger.error('🚨', 'Error processing notification event in preference filter', {
                error,
                message: message.value?.toString(),
            })
        }

        await heartbeat()
    }

    const duration = Date.now() - startTime
    logger.info('🔔', 'Preference filter batch processed', {
        events: batch.messages.length,
        user_dispatches: totalUserDispatches,
        duration_ms: duration,
    })
}

async function checkUserPreference(
    userId: number,
    teamId: number,
    resourceType: string,
    redis: Redis,
    postgres: PostgresRouter
): Promise<boolean> {
    // Try cache first
    const cacheKey = `notif_prefs:${userId}:${teamId}`
    const cached = await redis.get(cacheKey)

    if (cached) {
        const prefs: UserPreferences = JSON.parse(cached)
        // Default to true (opt-in) if no explicit preference
        return prefs[resourceType] !== undefined ? prefs[resourceType] : true
    }

    // Cache miss - query database
    const result = await postgres.query(
        PostgresUse.COMMON_READ,
        `SELECT resource_type, enabled FROM posthog_notification_preference
        WHERE user_id = $1 AND team_id = $2`,
        [userId, teamId],
        'getUserNotificationPreferences'
    )

    const prefs: UserPreferences = {}
    for (const row of result.rows) {
        prefs[row.resource_type] = row.enabled
    }

    // Cache for future lookups (no expiration)
    await redis.set(cacheKey, JSON.stringify(prefs))

    // Default to true (opt-in) if no explicit preference
    return prefs[resourceType] !== undefined ? prefs[resourceType] : true
}

function makeHealthCheck(consumer: Consumer, sessionTimeout: number): () => Promise<HealthCheckResult> {
    const { HEARTBEAT } = consumer.events
    let lastHeartbeat: number = Date.now()
    consumer.on(HEARTBEAT, ({ timestamp }) => (lastHeartbeat = timestamp))

    const isHealthy = async () => {
        const milliSecondsToLastHeartbeat = Date.now() - lastHeartbeat
        if (milliSecondsToLastHeartbeat < sessionTimeout) {
            return new HealthCheckResultOk()
        }

        try {
            const { state } = await consumer.describeGroup()

            if (['CompletingRebalance', 'PreparingRebalance'].includes(state)) {
                return new HealthCheckResultDegraded('Consumer group is rebalancing', { state })
            }

            return new HealthCheckResultOk()
        } catch (error) {
            logger.error('🚨', 'Error checking preference filter consumer group state', { error })
            return new HealthCheckResultError('Error checking consumer group state', { error })
        }
    }
    return isHealthy
}
