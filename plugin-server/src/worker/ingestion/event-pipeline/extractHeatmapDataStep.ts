import { URL } from 'url'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { PreIngestionEvent, RawClickhouseHeatmapEvent, TimestampFormat } from '../../../types'
import { status } from '../../../utils/status'
import { castTimestampOrNow } from '../../../utils/utils'
import { isDistinctIdIllegal } from '../person-state'
import { captureIngestionWarning } from '../utils'
import { EventPipelineRunner } from './runner'

// This represents the scale factor for the heatmap data. Essentially how much we are reducing the resolution by.
const SCALE_FACTOR = 16

type HeatmapDataItem = {
    x: number
    y: number
    target_fixed: boolean
    type: string
}

type HeatmapData = Record<string, HeatmapDataItem[]>

export function extractHeatmapDataStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent
): Promise<[PreIngestionEvent, Promise<void>[]]> {
    const { eventUuid, teamId } = event

    let acks: Promise<void>[] = []

    try {
        const heatmapEvents = extractScrollDepthHeatmapData(event) ?? []

        // eslint-disable-next-line @typescript-eslint/no-floating-promises
        acks = heatmapEvents.map((rawEvent) => {
            return runner.hub.kafkaProducer.produce({
                topic: runner.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                key: eventUuid,
                value: Buffer.from(JSON.stringify(rawEvent)),
                waitForAck: true,
            })
        })
    } catch (e) {
        acks.push(
            captureIngestionWarning(runner.hub.kafkaProducer, teamId, 'invalid_heatmap_data', {
                eventUuid,
            })
        )
    }

    // We don't want to ingest this data to the events table
    delete event.properties['$heatmap_data']

    return Promise.resolve([event, acks])
}

function replacePathInUrl(url: string, newPath: string): string {
    const parsedUrl = new URL(url)
    parsedUrl.pathname = newPath
    return parsedUrl.toString()
}

function isValidString(x: unknown): x is string {
    return typeof x === 'string' && !!x.trim().length
}

function isValidNumber(n: unknown): n is number {
    return typeof n === 'number' && !isNaN(n)
}

function extractScrollDepthHeatmapData(event: PreIngestionEvent): RawClickhouseHeatmapEvent[] {
    function drop(cause: string): RawClickhouseHeatmapEvent[] {
        eventDroppedCounter
            .labels({
                event_type: 'heatmap_event_extraction',
                drop_cause: cause,
            })
            .inc()
        return []
    }

    const { teamId, timestamp, properties, distinctId } = event
    const {
        $viewport_height,
        $viewport_width,
        $session_id,
        $prev_pageview_pathname,
        $prev_pageview_max_scroll,
        $current_url,
        $heatmap_data,
    } = properties || {}

    let heatmapData = $heatmap_data as HeatmapData | null

    if ($prev_pageview_pathname && $current_url) {
        // We are going to add the scroll depth info derived from the previous pageview to the current pageview's heatmap data
        if (!heatmapData) {
            heatmapData = {}
        }

        const previousUrl = replacePathInUrl($current_url, $prev_pageview_pathname)
        heatmapData[previousUrl] = heatmapData[previousUrl] || []
        heatmapData[previousUrl].push({
            x: 0,
            y: $prev_pageview_max_scroll,
            target_fixed: false,
            type: 'scrolldepth',
        })
    }

    let heatmapEvents: RawClickhouseHeatmapEvent[] = []

    if (!heatmapData || Object.entries(heatmapData).length === 0) {
        return []
    }

    if (!isValidString(distinctId) || isDistinctIdIllegal(distinctId)) {
        return drop('invalid_distinct_id')
    }

    if (!isValidNumber($viewport_height) || !isValidNumber($viewport_width)) {
        status.warn('👀', '[extract-heatmap-data] dropping because invalid viewport dimensions', {
            parent: event.event,
            teamId: teamId,
            eventTimestamp: timestamp,
            $viewport_height,
            $viewport_width,
        })
        return drop('invalid_viewport_dimensions')
    }

    Object.entries(heatmapData).forEach(([url, items]) => {
        if (!isValidString(url)) {
            return
        }

        if (Array.isArray(items)) {
            heatmapEvents = heatmapEvents.concat(
                (items as any[])
                    .map(
                        (hme: {
                            x: number
                            y: number
                            target_fixed: boolean
                            type: string
                        }): RawClickhouseHeatmapEvent | null => {
                            if (!isValidNumber(hme.x) || !isValidNumber(hme.y) || !isValidString(hme.type)) {
                                return null
                            }

                            return {
                                type: hme.type,
                                x: Math.round(hme.x / SCALE_FACTOR),
                                y: Math.round(hme.y / SCALE_FACTOR),
                                pointer_target_fixed: hme.target_fixed,
                                viewport_height: Math.round($viewport_height / SCALE_FACTOR),
                                viewport_width: Math.round($viewport_width / SCALE_FACTOR),
                                current_url: String(url),
                                session_id: String($session_id),
                                scale_factor: SCALE_FACTOR,
                                timestamp: castTimestampOrNow(timestamp ?? null, TimestampFormat.ClickHouse),
                                team_id: teamId,
                                distinct_id: distinctId,
                            }
                        }
                    )
                    .filter((x): x is RawClickhouseHeatmapEvent => x !== null)
            )
        }
    })

    return heatmapEvents
}
