import { createClient } from '@clickhouse/client'
import * as fs from 'fs'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'
import * as path from 'path'
import { PluginsServerConfig } from 'types'

import {
    KAFKA_APP_METRICS,
    KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_JSON_DLQ,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
    KAFKA_SESSION_RECORDING_EVENTS,
} from '../../config/kafka-topics'
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

    const topicToTable = {
        [KAFKA_EVENTS_JSON]: 'writable_events',
        [KAFKA_EVENTS_DEAD_LETTER_QUEUE]: 'events_dead_letter_queue',
        [KAFKA_GROUPS]: 'groups',
        [KAFKA_PERSON]: 'person',
        [KAFKA_PERSON_DISTINCT_ID]: 'person_distinct_id2',
        [KAFKA_PLUGIN_LOG_ENTRIES]: 'plugin_log_entries',
        [KAFKA_SESSION_RECORDING_EVENTS]: 'writable_session_recording_events',
        [KAFKA_INGESTION_WARNINGS]: 'sharded_ingestion_warnings',
        [KAFKA_APP_METRICS]: 'sharded_app_metrics',
    } as const

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })

        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                })
                await producer.send({ topic: KAFKA_EVENTS_JSON_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            try {
                const row = JSON.parse(message.value.toString())

                status.debug('⬆️', 'Inserting row', { row })

                await clickhouse.insert({
                    table: topicToTable[batch.topic as keyof typeof topicToTable],
                    values: [row],
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
    await consumer.subscribe({
        topics: Object.keys(topicToTable),
    })
    await consumer.run({
        eachBatchAutoResolve: false,
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_EVENTS_JSON, eachBatch, payload, statsd)
        },
    })

    return consumer
}
