import { Consumer, EachBatchPayload } from 'kafkajs'

import { KAFKA_NOTIFICATION_USER_DISPATCH, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
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

interface UserNotificationDispatch {
    user_id: number
    team_id: number
    resource_type: string
    event_type: string
    resource_id: string | null
    title: string
    message: string
    context: Record<string, any>
    priority: string
    original_event_id: string
}

export const startNotificationsConsumer = async (hub: Hub): Promise<PluginServerService> => {
    logger.info('🔔', 'Starting notifications user dispatch consumer (Stage 3)')

    const { kafka, postgres } = hub
    const djangoUrl = process.env.DJANGO_URL || 'http://localhost:8000'

    let inflightBatch: Promise<void> | null = null

    const consumer = kafka.consumer({
        groupId: `${KAFKA_PREFIX}notification-user-dispatch`,
        sessionTimeout: hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
        rebalanceTimeout: hub.KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS ?? undefined,
        readUncommitted: false,
    })
    setupEventHandlers(consumer)

    await consumer.subscribe({ topic: KAFKA_NOTIFICATION_USER_DISPATCH, fromBeginning: false })
    await consumer.run({
        eachBatch: async (payload) => {
            inflightBatch = eachBatchNotifications(payload, postgres, djangoUrl, hub)
            await inflightBatch
            inflightBatch = null
        },
    })

    const onShutdown = async () => {
        try {
            await consumer.stop()
        } catch (e) {
            logger.error('🚨', 'Error stopping notifications consumer', e)
        }
        if (inflightBatch) {
            logger.info('🔔', 'Waiting for in-flight notification batch to complete...')
            await inflightBatch
        }
        try {
            await consumer.disconnect()
        } catch (e) {
            logger.error('🚨', 'Error disconnecting notifications consumer', e)
        }
    }

    return {
        id: 'notifications-consumer',
        healthcheck: makeHealthCheck(consumer, hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS),
        onShutdown,
    }
}

async function eachBatchNotifications(
    { batch, heartbeat }: EachBatchPayload,
    postgres: PostgresRouter,
    djangoUrl: string,
    hub: Hub
): Promise<void> {
    const startTime = Date.now()

    for (const message of batch.messages) {
        if (!message.value) {
            continue
        }

        try {
            const event: UserNotificationDispatch = JSON.parse(message.value.toString())

            // Generate UUID in JavaScript since gen_random_uuid() requires pgcrypto extension
            const { randomUUID } = await import('crypto')
            const notificationId = randomUUID()

            const result = await postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_notification
                (id, user_id, team_id, resource_type, resource_id, title, message, context, priority, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                RETURNING id, user_id, team_id, resource_type, resource_id, title, message, context, priority, created_at`,
                [
                    notificationId,
                    event.user_id,
                    event.team_id,
                    event.resource_type,
                    event.resource_id,
                    event.title,
                    event.message,
                    JSON.stringify(event.context),
                    event.priority,
                ],
                'createNotification'
            )

            const notification = result.rows[0]

            logger.info('🔔', 'Notification created in DB', {
                notification_id: notification.id,
                user_id: event.user_id,
                title: event.title,
            })

            const notificationData = {
                id: notification.id,
                resource_type: notification.resource_type,
                resource_id: notification.resource_id,
                title: notification.title,
                message: notification.message,
                context: notification.context,
                priority: notification.priority,
                created_at:
                    notification.created_at instanceof Date
                        ? notification.created_at.toISOString()
                        : notification.created_at,
            }

            // Broadcast via Redis Pub/Sub directly to WebSocket consumers
            try {
                const redisClient = await hub.redisPool.acquire()
                const redisChannel = `posthog:notifications:user:${event.user_id}`

                console.log('🔔🔔🔔 REDIS BROADCAST START:', redisChannel, 'user:', event.user_id)

                logger.info('🔔', 'Attempting Redis WebSocket broadcast', {
                    redis_channel: redisChannel,
                    user_id: event.user_id,
                    notification_id: notification.id,
                })

                // Publish notification directly to Redis pub/sub
                const publishCount = await redisClient.publish(redisChannel, JSON.stringify(notificationData))

                await hub.redisPool.release(redisClient)

                const response = { ok: publishCount > 0, status: 200, statusText: 'OK' }

                console.log('🔔🔔🔔 BROADCAST RESPONSE:', response.status, response.statusText)

                if (!response.ok) {
                    console.log('🚨🚨🚨 BROADCAST FAILED:', response.status)
                    logger.error('🚨', 'WebSocket broadcast failed', {
                        status: response.status,
                        statusText: response.statusText,
                        user_id: event.user_id,
                        notification_id: notification.id,
                    })
                } else {
                    console.log('✅✅✅ BROADCAST SUCCESS!')
                    logger.info('✅', 'WebSocket broadcast SUCCESS', {
                        original_event_id: event.original_event_id,
                        user_id: event.user_id,
                        notification_id: notification.id,
                        status: response.status,
                    })
                }
            } catch (broadcastError) {
                logger.error('🚨', 'WebSocket broadcast request failed', {
                    error: broadcastError,
                    user_id: event.user_id,
                    notification_id: notification.id,
                })
            }

            logger.debug('🔔', 'Notification saved to DB', {
                original_event_id: event.original_event_id,
                user_id: event.user_id,
                notification_id: notification.id,
            })
        } catch (error) {
            logger.error('🚨', 'Error processing notification event', {
                error:
                    error instanceof Error
                        ? {
                              name: error.name,
                              message: error.message,
                              stack: error.stack,
                          }
                        : String(error),
                rawMessage: message.value?.toString(),
            })
        }

        await heartbeat()
    }

    const duration = Date.now() - startTime
    logger.info('🔔', 'Batch processed', {
        count: batch.messages.length,
        duration_ms: duration,
    })
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
            logger.error('🚨', 'Error checking notifications consumer group state', { error })
            return new HealthCheckResultError('Error checking consumer group state', { error })
        }
    }
    return isHealthy
}
