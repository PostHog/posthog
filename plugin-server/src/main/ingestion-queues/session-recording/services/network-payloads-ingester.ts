import { HighLevelProducer as RdKafkaProducer } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { PluginsServerConfig, RRWebEvent } from '../../../../types'
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

export interface ClickHousePerformanceEvent {
    uuid: string
    timestamp: string | number
    distinct_id: string
    session_id: string
    window_id: string
    pageview_id: string
    current_url: string

    // BASE_EVENT_COLUMNS
    time_origin?: string
    entry_type?: string
    name?: string

    // RESOURCE_EVENT_COLUMNS
    start_time?: number
    duration?: number
    redirect_start?: number
    redirect_end?: number
    worker_start?: number
    fetch_start?: number
    domain_lookup_start?: number
    domain_lookup_end?: number
    connect_start?: number
    secure_connection_start?: number
    connect_end?: number
    request_start?: number
    response_start?: number
    response_end?: number
    decoded_body_size?: number
    encoded_body_size?: number

    initiator_type?: string
    next_hop_protocol?: string
    render_blocking_status?: string
    response_status?: number
    // see https://developer.mozilla.org/en-US/docs/Web/API/PerformanceResourceTiming/transferSize
    // zero has meaning for this field so should not be used unless the transfer size was known to be zero
    transfer_size?: number

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    largest_contentful_paint_element?: string
    largest_contentful_paint_render_time?: number
    largest_contentful_paint_load_time?: number
    largest_contentful_paint_size?: number
    largest_contentful_paint_id?: string
    largest_contentful_paint_url?: string

    // NAVIGATION_EVENT_COLUMNS
    dom_complete?: number
    dom_content_loaded_event?: number
    dom_interactive?: number
    load_event_end?: number
    load_event_start?: number
    redirect_count?: number
    navigation_type?: string
    unload_event_end?: number
    unload_event_start?: number

    // request/response capture - merged in from rrweb/network@1 payloads
    // we don't want these in ClickHouse because of size
    // request_headers?: Record<string, string>
    // response_headers?: Record<string, string>
    // request_body?: Body
    // response_body?: Body
    method?: string
    is_initial?: boolean
}

export class NetworkPayloadsIngester extends BaseIngester {
    private readonly enabledTeams: number[] | true | false

    constructor(
        config: PluginsServerConfig,
        producer: RdKafkaProducer,
        persistentHighWaterMarker?: OffsetHighWaterMarker
    ) {
        super('session_replay_network_payloads_ingester', producer, persistentHighWaterMarker)

        try {
            const splat = config.SESSION_RECORDING_NETWORK_PAYLOADS_ENABLED_TEAMS.split(',')
            if (splat.length === 0) {
                this.enabledTeams = false
            } else if (splat.some((s) => s === '*')) {
                this.enabledTeams = true
            } else {
                this.enabledTeams = splat.map((s) => parseInt(s, 10))
            }
        } catch (e) {
            status.warn('🔴', 'could not parse enabled teams', e)
            this.enabledTeams = false
        }
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
            const networkPayloads = extractNetworkPayloadsFrom(rrwebEvents, event.team_id, event.session_id)
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

function extractNetworkPayloadsFrom(
    rrwebEvents: RRWebEvent[],
    _teamId: number,
    _sessionId: string
): ClickHousePerformanceEvent[] {
    for (const event of rrwebEvents) {
        if (event.type === 6 && event.data.plugin === 'rrweb/network@1') {
            // we want to map event.data to a shape we can ingest to ClickHouse
            // we don't want request or response bodies
        }
    }
    return []
}
