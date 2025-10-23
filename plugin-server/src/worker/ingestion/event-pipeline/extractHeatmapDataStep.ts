import { URL } from 'url'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { PreIngestionEvent, RawClickhouseHeatmapEvent, TimestampFormat } from '../../../types'
import { logger } from '../../../utils/logger'
import { castTimestampOrNow } from '../../../utils/utils'
import { isDistinctIdIllegal } from '../persons/person-merge-service'
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

export async function extractHeatmapDataStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent
): Promise<[PreIngestionEvent, Promise<unknown>[]]> {
    const { eventUuid, teamId } = event

    const acks: Promise<unknown>[] = []

    try {
        const team = await runner.hub.teamManager.getTeam(teamId)

        if (team?.heatmaps_opt_in !== false) {
            const heatmapEvents = (await extractScrollDepthHeatmapData(event, runner)) ?? []

            if (heatmapEvents.length > 0) {
                acks.push(
                    runner.hub.kafkaProducer.queueMessages({
                        topic: runner.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                        messages: heatmapEvents.map((rawEvent) => ({
                            key: eventUuid,
                            value: JSON.stringify(rawEvent),
                        })),
                    })
                )
            }
        }
    } catch (e) {
        acks.push(
            captureIngestionWarning(runner.hub.kafkaProducer, teamId, 'invalid_heatmap_data', {
                eventUuid,
            })
        )
    }

    // We don't want to ingest this data to the events table
    delete event.properties['$heatmap_data']

    return [event, acks]
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

function isValidBoolean(b: unknown): b is boolean {
    return typeof b === 'boolean'
}

async function extractScrollDepthHeatmapData(
    event: PreIngestionEvent,
    runner: EventPipelineRunner
): Promise<RawClickhouseHeatmapEvent[]> {
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
        logger.warn('👀', '[extract-heatmap-data] dropping because invalid viewport dimensions', {
            parent: event.event,
            teamId: teamId,
            eventTimestamp: timestamp,
            $viewport_height,
            $viewport_width,
        })
        return drop('invalid_viewport_dimensions')
    }

    const promises = Object.entries(heatmapData).map(async ([url, items]) => {
        if (!isValidString(url)) {
            await captureIngestionWarning(
                runner.hub.kafkaProducer,
                teamId,
                'rejecting_heatmap_data_with_invalid_url',
                {
                    heatmapUrl: url,
                    session_id: $session_id,
                },
                { key: $session_id }
            )
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
                            if (
                                !isValidNumber(hme.x) ||
                                !isValidNumber(hme.y) ||
                                !isValidString(hme.type) ||
                                !isValidBoolean(hme.target_fixed)
                            ) {
                                // TODO really we should add an ingestion warning here, but no urgency
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
        } else {
            await captureIngestionWarning(
                runner.hub.kafkaProducer,
                teamId,
                'rejecting_heatmap_data_with_invalid_items',
                {
                    heatmapUrl: url,
                    session_id: $session_id,
                },
                { key: $session_id }
            )
        }
    })

    await Promise.all(promises)

    return heatmapEvents
}
