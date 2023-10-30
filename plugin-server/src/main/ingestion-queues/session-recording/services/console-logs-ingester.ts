import { captureException } from '@sentry/node'
import { HighLevelProducer as RdKafkaProducer, NumberNullUndefined } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KAFKA_LOG_ENTRIES } from '../../../../config/kafka-topics'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../../../../kafka/config'
import { findOffsetsToCommit } from '../../../../kafka/consumer'
import { retryOnDependencyUnavailableError } from '../../../../kafka/error-handling'
import { createKafkaProducer, disconnectProducer, flushProducer, produce } from '../../../../kafka/producer'
import { PluginsServerConfig } from '../../../../types'
import { status } from '../../../../utils/status'
import { ConsoleLogEntry, gatherConsoleLogEvents, RRWebEventType } from '../../../../worker/ingestion/process-event'
import { eventDroppedCounter } from '../../metrics'
import { IncomingRecordingMessage } from '../types'
import { OffsetHighWaterMarker } from './offset-high-water-marker'

const HIGH_WATERMARK_KEY = 'session_replay_console_logs_events_ingester'

const consoleLogEventsCounter = new Counter({
    name: 'console_log_events_ingested',
    help: 'Number of console log events successfully ingested',
})

function deduplicateConsoleLogEvents(consoleLogEntries: ConsoleLogEntry[]): ConsoleLogEntry[] {
    // assuming that the console log entries are all for one team id (and they should be)
    // because we only use these for search
    // then we can deduplicate them by the message string

    const seen = new Set<string>()
    const deduped: ConsoleLogEntry[] = []

    for (const cle of consoleLogEntries) {
        const fingerPrint = `${cle.log_level}-${cle.message}`
        if (!seen.has(fingerPrint)) {
            deduped.push(cle)
            seen.add(fingerPrint)
        }
    }
    return deduped
}

// TODO this is an almost exact duplicate of the replay events ingester
// am going to leave this duplication and then collapse it when/if we add a performance events ingester
export class ConsoleLogsIngester {
    producer?: RdKafkaProducer
    enabled: boolean

    constructor(
        private readonly serverConfig: PluginsServerConfig,
        private readonly persistentHighWaterMarker: OffsetHighWaterMarker
    ) {
        this.enabled = serverConfig.SESSION_RECORDING_CONSOLE_LOGS_INGESTION_ENABLED
    }

    public async consumeBatch(messages: IncomingRecordingMessage[]) {
        const pendingProduceRequests: Promise<NumberNullUndefined>[] = []

        for (const message of messages) {
            const results = await retryOnDependencyUnavailableError(() => this.consume(message))
            if (results) {
                pendingProduceRequests.push(...results)
            }
        }

        // On each loop, we flush the producer to ensure that all messages
        // are sent to Kafka.
        try {
            await flushProducer(this.producer!)
        } catch (error) {
            // Rather than handling errors from flush, we instead handle
            // errors per produce request, which gives us a little more
            // flexibility in terms of deciding if it is a terminal
            // error or not.
        }

        // We wait on all the produce requests to complete. After the
        // flush they should all have been resolved/rejected already. If
        // we get an intermittent error, such as a Kafka broker being
        // unavailable, we will throw. We are relying on the Producer
        // already having handled retries internally.
        for (const produceRequest of pendingProduceRequests) {
            try {
                await produceRequest
            } catch (error) {
                status.error('🔁', '[console-log-events-ingester] main_loop_error', { error })

                if (error?.isRetriable) {
                    // We assume that if the error is retriable, then we
                    // are probably in a state where e.g. Kafka is down
                    // temporarily, and we would rather simply throw and
                    // have the process restarted.
                    throw error
                }
            }
        }

        const topicPartitionOffsets = findOffsetsToCommit(messages.map((message) => message.metadata))
        await Promise.all(
            topicPartitionOffsets.map((tpo) => this.persistentHighWaterMarker.add(tpo, HIGH_WATERMARK_KEY, tpo.offset))
        )
    }

    public async consume(event: IncomingRecordingMessage): Promise<Promise<number | null | undefined>[] | void> {
        if (!this.enabled) {
            return
        }

        const warn = (text: string, labels: Record<string, any> = {}) =>
            status.warn('⚠️', `[console-log-events-ingester] ${text}`, {
                offset: event.metadata.offset,
                partition: event.metadata.partition,
                ...labels,
            })

        const drop = (reason: string, labels: Record<string, any> = {}) => {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_console_log_events',
                    drop_cause: reason,
                })
                .inc()

            warn(reason, {
                reason,
                ...labels,
            })
        }

        // capture the producer so that TypeScript knows it's not null below this check
        const producer = this.producer
        if (!producer) {
            return drop('producer_not_ready')
        }

        if (
            await this.persistentHighWaterMarker.isBelowHighWaterMark(
                event.metadata,
                HIGH_WATERMARK_KEY,
                event.metadata.offset
            )
        ) {
            return drop('high_water_mark')
        }

        // cheapest possible check for any console logs to avoid parsing the events because...
        const hasAnyConsoleLogs = event.events.some(
            (e) => !!e && e.type === RRWebEventType.Plugin && e.data?.plugin === 'rrweb/console@1'
        )

        if (!hasAnyConsoleLogs) {
            return
        }

        // ... we don't want to mark events with no console logs as dropped
        // this keeps the signal here clean and makes it easier to debug
        // when we disable a team's console log ingestion
        if (!event.metadata.consoleLogIngestionEnabled) {
            return drop('console_log_ingestion_disabled')
        }

        try {
            const consoleLogEvents = deduplicateConsoleLogEvents(
                gatherConsoleLogEvents(event.team_id, event.session_id, event.events)
            )
            consoleLogEventsCounter.inc(consoleLogEvents.length)

            return consoleLogEvents.map((cle: ConsoleLogEntry) =>
                produce({
                    producer,
                    topic: KAFKA_LOG_ENTRIES,
                    value: Buffer.from(JSON.stringify(cle)),
                    key: event.session_id,
                })
            )
        } catch (error) {
            status.error('⚠️', '[console-log-events-ingester] processing_error', {
                error: error,
            })
            captureException(error, {
                tags: { source: 'console-log-events-ingester', team_id: event.team_id, session_id: event.session_id },
            })
        }
    }

    public async start(): Promise<void> {
        const connectionConfig = createRdConnectionConfigFromEnvVars(this.serverConfig)

        const producerConfig = createRdProducerConfigFromEnvVars(this.serverConfig)

        this.producer = await createKafkaProducer(connectionConfig, producerConfig)
        this.producer.connect()
    }

    public async stop(): Promise<void> {
        status.info('🔁', '[console-log-events-ingester] stopping')

        if (this.producer && this.producer.isConnected()) {
            status.info('🔁', '[console-log-events-ingester] disconnecting kafka producer in batchConsumer stop')
            await disconnectProducer(this.producer)
        }
    }
}
