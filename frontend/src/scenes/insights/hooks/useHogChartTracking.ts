import posthog from 'posthog-js'
import { useCallback, useRef } from 'react'

import type { OnChartPerformance } from 'lib/hog-charts'

interface HogChartTrackingMetadata {
    chart_type?: string
    insight_type?: string
    has_breakdown?: boolean
    insight_short_id?: string
    dashboard_id?: number
    in_shared_mode?: boolean
}

const FIRST_PAINT_EVENT = 'hog chart performance - first paint'

/** Captures hog-chart first-paint timing as a PostHog event. */
export function useHogChartTracking(metadata: HogChartTrackingMetadata): OnChartPerformance {
    const metadataRef = useRef(metadata)
    metadataRef.current = metadata

    return useCallback((event) => {
        if (event.phase !== 'first-paint') {
            return
        }
        posthog.capture(FIRST_PAINT_EVENT, {
            ...metadataRef.current,
            draw_ms: event.drawMs,
            since_mount_ms: event.sinceMountMs,
            series_count: event.seriesCount,
            data_point_count: event.dataPointCount,
        })
    }, [])
}
