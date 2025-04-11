import { PluginEvent } from '@posthog/plugin-scaffold'
import { URL } from 'url'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { RawClickhouseHeatmapEvent, TimestampFormat } from '../../../types'
import { logger } from '../../../utils/logger'
import { castTimestampOrNow } from '../../../utils/utils'
import { isDistinctIdIllegal } from '../../../worker/ingestion/person-state'

// This represents the scale factor for the heatmap data. Essentially how much we are reducing the resolution by.
const SCALE_FACTOR = 16

type HeatmapDataItem = {
    x: number
    y: number
    target_fixed: boolean
    type: string
}

type HeatmapData = Record<string, HeatmapDataItem[]>

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

export function extractHeatmapData(event: PluginEvent): RawClickhouseHeatmapEvent[] {
    function drop(cause: string): RawClickhouseHeatmapEvent[] {
        eventDroppedCounter
            .labels({
                event_type: 'heatmap_event_extraction',
                drop_cause: cause,
            })
            .inc()
        return []
    }

    const { team_id, timestamp, properties, distinct_id } = event
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

    if (!isValidString(distinct_id) || isDistinctIdIllegal(distinct_id)) {
        return drop('invalid_distinct_id')
    }

    if (!isValidNumber($viewport_height) || !isValidNumber($viewport_width)) {
        logger.warn('👀', '[extract-heatmap-data] dropping because invalid viewport dimensions', {
            parent: event.event,
            teamId: team_id,
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
                                team_id: team_id,
                                distinct_id: distinct_id,
                            }
                        }
                    )
                    .filter((x): x is RawClickhouseHeatmapEvent => x !== null)
            )
        }
    })

    return heatmapEvents
}
