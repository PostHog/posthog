import { HighLevelProducer as RdKafkaProducer } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { status } from '../../../../utils/status'
import { RRWebEventType } from '../process-event'
import { IncomingRecordingMessage } from '../types'
import { BaseIngester } from './base-ingester'
import { OffsetHighWaterMarker } from './offset-high-water-marker'

const HIGH_WATERMARK_KEY = 'session_replay_network_payloads_ingester'

const networkPayloadsEventsCounter = new Counter({
    name: 'network_payloads_ingested',
    help: 'Number of network payloads successfully ingested',
})
const payloadsPerMessageHistogram = new Histogram({
    name: 'network_payloads_per_message',
    help: 'a histogram of how many network payload events are extracted from each message processed',
})

export class NetworkPayloadsIngester extends BaseIngester {
    constructor(producer: RdKafkaProducer, persistentHighWaterMarker?: OffsetHighWaterMarker) {
        super('session_replay_network_payloads_ingester', producer, persistentHighWaterMarker)
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
        const hasAnyNetworkPayloads = rrwebEvents.some(
            (e) => !!e && e.type === RRWebEventType.Plugin && e.data?.plugin === 'rrweb/network@1'
        )

        if (!hasAnyNetworkPayloads) {
            return
        }

        // ... we don't want to mark events with no console logs as dropped
        // this keeps the signal here clean and makes it easier to debug
        // when we disable a team's console log ingestion
        if (!event.metadata.networkPayloadIngestionEnabled) {
            return this.drop('network_payload_ingestion_disabled')
        }

        try {
            const networkPayloads = []
            // const consoleLogEvents = deduplicateConsoleLogEvents(
            //     gatherConsoleLogEvents(event.team_id, event.session_id, rrwebEvents)
            // )
            networkPayloadsEventsCounter.inc(networkPayloads.length)
            payloadsPerMessageHistogram.observe(networkPayloads.length)
            //
            // return consoleLogEvents.map((cle: ConsoleLogEntry) =>
            //     produce({
            //         producer,
            //         topic: KAFKA_LOG_ENTRIES,
            //         value: Buffer.from(JSON.stringify(cle)),
            //         key: event.session_id,
            //         waitForAck: true,
            //     })
            // )
        } catch (error) {
            status.error('⚠️', `[${this.label}] processing_error`, {
                error: error,
            })
        }
    }
}
