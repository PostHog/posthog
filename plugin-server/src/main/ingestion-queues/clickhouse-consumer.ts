import { createClient } from '@clickhouse/client'
import * as fs from 'fs'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'
import * as path from 'path'
import { PluginsServerConfig } from 'types'

import { KAFKA_EVENTS_JSON, KAFKA_EVENTS_JSON_DLQ } from '../../config/kafka-topics'
import { status } from '../../utils/status'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

export const startClickHouseConsumer = async ({
    kafka,
    producer,
    serverConfig,
    statsd,
}: {
    kafka: Kafka
    producer: Producer
    serverConfig: PluginsServerConfig
    statsd?: StatsD
}) => {
    /*
        Consumer to insert events into ClickHouse.

        TODO: handle multiple topics/tables
        TODO: handle batching, assuming performance isn't good enough. The
        ClickHouse client supports inserting via a Stream but I'm not too
        familiar with these in Node. It looks like it should help with some
        batching though. See
        https://clickhouse.com/docs/en/integrations/language-clients/nodejs/#insert-method
        TODO: avoid parsing the JSON object events, we should just be able to
        pass through the JSON string.
    */

    const consumer = kafka.consumer({ groupId: 'clickhouse-inserter' })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting ClickHouse inserter consumer')

    const clickhouse = createClient({
        host: `${serverConfig.CLICKHOUSE_SECURE ? 'https' : 'http'}://${serverConfig.CLICKHOUSE_HOST}:${
            serverConfig.CLICKHOUSE_SECURE ? 8443 : 8123
        }`,
        username: serverConfig.CLICKHOUSE_USER,
        password: serverConfig.CLICKHOUSE_PASSWORD || undefined,
        database: serverConfig.CLICKHOUSE_DATABASE,
        tls: serverConfig.CLICKHOUSE_CA
            ? {
                  ca_cert: fs.readFileSync(path.join(serverConfig.BASE_DIR, serverConfig.CLICKHOUSE_CA)),
              }
            : undefined,
    })

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })

        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                    processEventAt: message.headers?.processEventAt,
                    eventId: message.headers?.eventId,
                })
                await producer.send({ topic: KAFKA_EVENTS_JSON_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            try {
                const event = JSON.parse(message.value.toString())

                status.debug('⬆️', 'Inserting event', { event })

                await clickhouse.insert({
                    table: 'writable_events',
                    values: [event],
                    format: 'JSONEachRow',
                })
            } catch (error) {
                if (error.name === 'ClickHouseError') {
                    // For errors relating to PostHog dependencies that are unavailable,
                    // e.g. Postgres, Kafka, Redis, we don't want to log the error to Sentry
                    // but rather bubble this up the stack for someone else to decide on
                    // what to do with it.
                    status.warn('⚠️', `Dependency unavailable for scheduled task`, { error: error.stack ?? error })
                    throw error
                }

                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    error: error.stack ?? error,
                })
                await producer.send({ topic: KAFKA_EVENTS_JSON_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            resolveOffset(message.offset)

            // After processing each message, we need to heartbeat to ensure
            // we don't get kicked out of the group. Note that although we call
            // this for each message, it's actually a no-op if we're not over
            // the heartbeatInterval.
            await heartbeat()
        }

        status.info('✅', 'Processed batch', { size: batch.messages.length })
    }

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_EVENTS_JSON })
    await consumer.run({
        eachBatchAutoResolve: false,
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_EVENTS_JSON, eachBatch, payload, statsd)
        },
    })

    return consumer
}
