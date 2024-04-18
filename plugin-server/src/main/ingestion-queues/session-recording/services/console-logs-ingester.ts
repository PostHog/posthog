import { HighLevelProducer as RdKafkaProducer } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KAFKA_LOG_ENTRIES } from '../../../../config/kafka-topics'
import { produce } from '../../../../kafka/producer'
import { status } from '../../../../utils/status'
import { ConsoleLogEntry, gatherConsoleLogEvents, RRWebEventType } from '../process-event'
import { IncomingRecordingMessage } from '../types'
import { BaseIngester } from './base-ingester'
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
        const fingerPrint = `${cle.level}-${cle.message}`
        if (!seen.has(fingerPrint)) {
            deduped.push(cle)
            seen.add(fingerPrint)
        }
    }
    return deduped
}

export class ConsoleLogsIngester extends BaseIngester {
    constructor(producer: RdKafkaProducer, persistentHighWaterMarker?: OffsetHighWaterMarker) {
        super(HIGH_WATERMARK_KEY, producer, persistentHighWaterMarker)
    }

    public async consume(event: IncomingRecordingMessage): Promise<Promise<number | null | undefined>[] | void> {
        // capture the producer so that TypeScript knows it's not null below this check
        const producer = this.producer
        if (!producer) {
            return this.drop('producer_not_ready')
        }

        if (
            await this.persistentHighWaterMarker?.isBelowHighWaterMark(
                event.metadata,
                HIGH_WATERMARK_KEY,
                event.metadata.highOffset
            )
        ) {
            return this.drop('high_water_mark')
        }

        const rrwebEvents = Object.values(event.eventsByWindowId).reduce((acc, val) => acc.concat(val), [])

        // cheapest possible check for any console logs to avoid parsing the events because...
        const hasAnyConsoleLogs = rrwebEvents.some(
            (e) => !!e && e.type === RRWebEventType.Plugin && e.data?.plugin === 'rrweb/console@1'
        )

        if (!hasAnyConsoleLogs) {
            return
        }

        try {
            const consoleLogEvents = deduplicateConsoleLogEvents(
                gatherConsoleLogEvents(event.team_id, event.session_id, rrwebEvents)
            )
            consoleLogEventsCounter.inc(consoleLogEvents.length)

            return consoleLogEvents.map((cle: ConsoleLogEntry) =>
                produce({
                    producer,
                    topic: KAFKA_LOG_ENTRIES,
                    value: Buffer.from(JSON.stringify(cle)),
                    key: event.session_id,
                    waitForAck: true,
                })
            )
        } catch (error) {
            status.error('⚠️', `[${this.label}] processing_error`, {
                error: error,
            })
        }
    }
}
