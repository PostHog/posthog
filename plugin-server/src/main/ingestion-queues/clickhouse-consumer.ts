import { createClient } from '@clickhouse/client'
import * as fs from 'fs'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, KafkaMessage, Producer } from 'kafkajs'
import * as path from 'path'
import { PluginsServerConfig } from 'types'

import {
    KAFKA_APP_METRICS,
    KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    KAFKA_EVENTS_JSON,
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
    topic,
    statsd,
}: {
    kafka: Kafka
    producer: Producer
    serverConfig: PluginsServerConfig
    topic: string
    statsd?: StatsD
}) => {
    /*
        Consumer to insert events into ClickHouse.

        TODO: handle batching, assuming performance isn't good enough. The
        ClickHouse client supports inserting via a Stream but I'm not too
        familiar with these in Node. It looks like it should help with some
        batching though. See
        https://clickhouse.com/docs/en/integrations/language-clients/nodejs/#insert-method
        TODO: avoid parsing the JSON object events, we should just be able to
        pass through the JSON string.
    */

    const consumer = kafka.consumer({ groupId: `clickhouse-inserter-${topic}` })
    setupEventHandlers(consumer)

    status.info('🔁', 'starting_clickhouse_consumer', { topic })

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

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })

        const messageJsonPairs: { message: KafkaMessage; json: Record<string, any> }[] = []

        const { tableName, dlq, maxChunkSize } = topicToTable[batch.topic as keyof typeof topicToTable]

        // The dead letter queue to which we should send messages that fail to
        // be inserted. Note that in some cases, e.g. for the actual dead letter
        // queue we do not want to send to a dead letter queue, in which case
        // the `deadLetterQueue` will be null.
        const deadLetterQueue = dlq !== false ? `${batch.topic}_inserter_dlq` : null

        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                    topic: batch.topic,
                    table: tableName,
                    deadLetterQueue,
                })

                if (deadLetterQueue) {
                    await producer.send({ topic: deadLetterQueue, messages: [message] })
                }

                continue
            }

            try {
                messageJsonPairs.push({ message, json: JSON.parse(message.value.toString()) })
            } catch (error) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    error,
                    stack: error.stack,
                    topic: batch.topic,
                    table: tableName,
                    deadLetterQueue,
                })

                if (deadLetterQueue) {
                    await producer.send({ topic: deadLetterQueue, messages: [message] })
                }

                continue
            }
        }

        // NOTE: there is one table, `plugin_log_entries`, that is partitioned
        // by plugin_id. This means that if we try to insert log entries for
        // more than 100 plugins, we end up getting an error, at least with
        // ClickHouse's `max_partitions_per_insert_block` set to the default of
        // 100, that there are too many partitions in the insert block.
        //
        // TODO: update plugin_log_entries to not be partitioned by plugin_id
        //
        // TODO: handle checking the Schema of the JSON object up front before
        // sending to ClickHouse.
        //
        // TODO: handle only sending to DQL for only those messages that were
        // failed to insert from ClickHouse. I'm not exactly sure how this
        // works, but I assume that there is a way to see which specific
        // messages in a chunk had failed. At the moment we send all messages in
        // a chunk to the DQL, which is not ideal.
        while (true) {
            const chunk = maxChunkSize
                ? messageJsonPairs.splice(0, maxChunkSize)
                : messageJsonPairs.splice(0, messageJsonPairs.length)

            if (chunk.length === 0) {
                break
            }

            try {
                await clickhouse.insert({
                    table: tableName,
                    values: chunk.map(({ json }) => json),
                    format: 'JSONEachRow',
                })

                const lastPair = chunk.pop()
                if (lastPair) {
                    resolveOffset(lastPair.message.offset)
                }
            } catch (error) {
                if (Object.values(retriableErrorCodes).includes(error.code)) {
                    // For errors relating to transient ClickHouse issues, do
                    // not progress the offset, rather have the KafkaJS retry
                    // mechanism kick in.
                    status.warn('⚠️', `Dependency unavailable`, {
                        topic: batch.topic,
                        tableName,
                        error,
                        stack: error.stack,
                        size: messageJsonPairs.length,
                    })

                    // If we have a transient error with ClickHouse, we:
                    //
                    //  1. pause the topic
                    //  2. set a timer to resume shortly
                    //  3. return, with the knowledge that the consumer is set
                    //     to not commit offsets automatically.
                    //
                    consumer.pause([{ topic: batch.topic }])
                    setTimeout(() => consumer.resume([{ topic: batch.topic }]), 1000)
                    return
                }

                status.error('⚠️', `Failed to insert`, {
                    error,
                    stack: error.stack,
                    topic: batch.topic,
                    tableName,
                    size: batch.messages.length,
                    deadLetterQueue,
                })

                if (deadLetterQueue) {
                    await producer.send({
                        topic: deadLetterQueue,
                        messages: chunk.map(({ message }) => message),
                    })
                }

                const lastPair = chunk.pop()
                if (lastPair) {
                    resolveOffset(lastPair.message.offset)
                }
            }
        }

        // If we get to the bottom,
        resolveOffset(batch.messages.slice(-1)[0].offset)

        status.info('✅', 'Inserted batch batch', { size: batch.messages.length, topic: batch.topic, tableName })
    }

    await consumer.connect()
    await consumer.subscribe({ topics: [topic] })
    await consumer.run({
        eachBatchAutoResolve: false,
        eachBatch: async (payload) => {
            return await instrumentEachBatch(topic, eachBatch, payload, statsd)
        },
    })

    return consumer
}

const topicToTable: { [key: string]: { tableName: string; dlq?: boolean; maxChunkSize?: number } } = {
    [KAFKA_EVENTS_JSON]: { tableName: 'writable_events' },
    [KAFKA_EVENTS_DEAD_LETTER_QUEUE]: {
        tableName: 'events_dead_letter_queue',
        // For the DLQ, don't try to insert into another dlq. We use `null`
        // to signify this.
        dlq: false,
    },
    [KAFKA_GROUPS]: { tableName: 'groups' },
    [KAFKA_PERSON]: { tableName: 'person' },
    [KAFKA_PERSON_DISTINCT_ID]: { tableName: 'person_distinct_id2' },
    [KAFKA_PLUGIN_LOG_ENTRIES]: {
        tableName: 'plugin_log_entries',
        // NOTE: plugin_log_entries is PARTITIONED BY plugin_id, and as such we end
        // up hitting the max number of partitions involved in an insert, a
        // ClickHouse setting.
        maxChunkSize: 100,
    },
    [KAFKA_SESSION_RECORDING_EVENTS]: { tableName: 'writable_session_recording_events' },
    [KAFKA_INGESTION_WARNINGS]: { tableName: 'sharded_ingestion_warnings' },
    [KAFKA_APP_METRICS]: {
        // NOTE: we are writing to a "non-live" table here to validate the
        // approach highlighted on https://github.com/PostHog/posthog/pull/13049
        // to not use KafkaTables in ClickHouse.
        tableName: 'sharded_app_metrics_inserter',
    },
} as const

const retriableErrorCodes = {
    TABLE_IS_READ_ONLY: '42',
    UNKNOWN_STATUS_OF_INSERT: '319',
    KEEPER_EXCEPTION: '999',
    POCO_EXCEPTION: '1000',
} as const
