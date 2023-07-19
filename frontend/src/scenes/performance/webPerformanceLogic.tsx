import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { PerformanceEvent, PerformancePageView } from '~/types'
import type { webPerformanceLogicType } from './webPerformanceLogicType'
import { getSeriesColor } from 'lib/colors'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

export enum WebPerformancePage {
    TABLE = 'table',
    WATERFALL_CHART = 'waterfall_chart',
}

export interface EventPerformanceMeasure {
    start: number
    end: number
    color: string
    reducedHeight?: boolean
}

export interface PointInTimeMarker {
    marker: string
    time: number
    color: string
}

export interface EventPerformanceData {
    pointsInTime: PointInTimeMarker[]
    resourceTimings: ResourceTiming[]
    maxTime: number
    gridMarkers: number[]
    timestamp: string
}

function colorForEntry(entryType: string | undefined): string {
    switch (entryType) {
        case 'domComplete':
            return getSeriesColor(1)
        case 'domInteractive':
            return getSeriesColor(2)
        case 'pageLoaded':
            return getSeriesColor(3)
        case 'first-contentful-paint':
            return getSeriesColor(4)
        case 'css':
            return getSeriesColor(6)
        case 'xmlhttprequest':
            return getSeriesColor(7)
        case 'fetch':
            return getSeriesColor(8)
        case 'other':
            return getSeriesColor(9)
        case 'script':
            return getSeriesColor(10)
        case 'link':
            return getSeriesColor(11)
        case 'first-paint':
            return getSeriesColor(11)
        default:
            return getSeriesColor(13)
    }
}

export interface ResourceTiming {
    item: string | URL
    entry: PerformanceEvent
    performanceParts: Record<string, EventPerformanceMeasure>
    color?: string
}

/**
 * There are defined sections to performance measurement. We may have data for some or all of them
 *
 * 1) Redirect
 *  - from startTime which would also be redirectStart
 *  - until redirect_end
 *
 *  2) App Cache
 *   - from fetch_start
 *   - until domain_lookup_start
 *
 *  3) DNS
 *   - from domain_lookup_start
 *   - until domain_lookup_end
 *
 *  4) TCP
 *   - from connect_start
 *   - until connect_end
 *
 *   this contains any time to negotiate SSL/TLS
 *   - from secure_connection_start
 *   - until connect_end
 *
 *  5) Request
 *   - from request_start
 *   - until response_start
 *
 *  6) Response
 *   - from response_start
 *   - until response_end
 *
 *  7) Document Processing
 *   - from response_end
 *   - until load_event_end
 *
 * see https://nicj.net/resourcetiming-in-practice/
 *
 * @param perfEntry
 * @param maxTime
 */
function calculatePerformanceParts(
    perfEntry: PerformanceEvent,
    maxTime: number
): {
    performanceParts: Record<string, EventPerformanceMeasure>
    maxTime: number
} {
    const performanceParts: Record<string, EventPerformanceMeasure> = {}

    if (perfEntry.redirect_start && perfEntry.redirect_end) {
        performanceParts['redirect'] = {
            start: perfEntry.redirect_start,
            end: perfEntry.redirect_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
        maxTime = Math.max(maxTime, perfEntry.redirect_end)
    }

    if (perfEntry.fetch_start && perfEntry.domain_lookup_start) {
        performanceParts['app cache'] = {
            start: perfEntry.fetch_start,
            end: perfEntry.domain_lookup_start,
            color: colorForEntry(perfEntry.initiator_type),
        }
        maxTime = Math.max(maxTime, perfEntry.redirect_end || -1)
    }

    if (perfEntry.domain_lookup_end && perfEntry.domain_lookup_start) {
        performanceParts['dns lookup'] = {
            start: perfEntry.domain_lookup_start,
            end: perfEntry.domain_lookup_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
        maxTime = Math.max(maxTime, perfEntry.domain_lookup_end)
    }

    if (perfEntry.connect_end && perfEntry.connect_start) {
        performanceParts['connection time'] = {
            start: perfEntry.connect_start,
            end: perfEntry.connect_end,
            color: colorForEntry(perfEntry.initiator_type),
        }

        if (perfEntry.secure_connection_start) {
            performanceParts['tls time'] = {
                start: perfEntry.secure_connection_start,
                end: perfEntry.connect_end,
                color: colorForEntry(perfEntry.initiator_type),
                reducedHeight: true,
            }
        }
        maxTime = Math.max(maxTime, perfEntry.connect_end)
    }

    if (perfEntry.response_start && perfEntry.request_start) {
        performanceParts['waiting for first byte (TTFB)'] = {
            start: perfEntry.request_start,
            end: perfEntry.response_start,
            color: colorForEntry(perfEntry.initiator_type),
        }
        maxTime = Math.max(maxTime, perfEntry.response_start)
    }

    if (perfEntry.response_start && perfEntry.response_end) {
        performanceParts['receiving response'] = {
            start: perfEntry.response_start,
            end: perfEntry.response_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
        maxTime = Math.max(maxTime, perfEntry.response_end)
    }

    if (perfEntry.response_end && perfEntry.load_event_end) {
        performanceParts['document processing'] = {
            start: perfEntry.response_end,
            end: perfEntry.load_event_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
        maxTime = Math.max(maxTime, perfEntry.load_event_end)
    }

    return { performanceParts, maxTime }
}

// only exported so it doesn't complain about being unused
// TODO launch waterfall chart from replay screen
export function forWaterfallDisplay(pageviewEvents: PerformanceEvent[] | null): EventPerformanceData {
    let maxTime = 0
    const pointsInTime: PointInTimeMarker[] = []
    const resourceTimings: ResourceTiming[] = []
    let timestamp: number | string | null = null

    pageviewEvents?.forEach((performanceEvent) => {
        if (performanceEvent.entry_type === 'navigation') {
            timestamp = performanceEvent.timestamp

            if (performanceEvent?.dom_complete) {
                pointsInTime.push({
                    marker: 'domComplete',
                    time: performanceEvent.dom_complete,
                    color: colorForEntry('domComplete'),
                })
            }
            if (performanceEvent?.dom_interactive) {
                pointsInTime.push({
                    marker: 'domInteractive',
                    time: performanceEvent.dom_interactive,
                    color: colorForEntry('domInteractive'),
                })
            }

            if (performanceEvent?.duration) {
                pointsInTime.push({
                    marker: 'pageLoaded',
                    time: performanceEvent.duration,
                    color: colorForEntry('pageLoaded'),
                })
                maxTime = Math.max(performanceEvent.duration, maxTime)
            }

            const navigationPerformanceParts = calculatePerformanceParts(performanceEvent, maxTime)
            resourceTimings.push({
                item: performanceEvent.name ? new URL(performanceEvent.name) : 'unknown',
                performanceParts: navigationPerformanceParts.performanceParts,
                entry: performanceEvent,
            })
            maxTime = Math.max(maxTime, navigationPerformanceParts.maxTime)
        }
        if (
            performanceEvent.entry_type === 'paint' &&
            !!performanceEvent.name &&
            performanceEvent.start_time !== undefined
        ) {
            pointsInTime.push({
                marker: performanceEvent.name,
                time: performanceEvent.start_time,
                color: colorForEntry(performanceEvent.name),
            })
            maxTime = performanceEvent.start_time > maxTime ? performanceEvent.start_time : maxTime
        }
        if (performanceEvent.entry_type === 'resource') {
            if (!timestamp) {
                timestamp = performanceEvent.timestamp
            }

            const resourceURL = performanceEvent.name ? new URL(performanceEvent.name) : 'unknown'
            const resourcePerformanceParts = calculatePerformanceParts(performanceEvent, maxTime)
            const next = {
                item: resourceURL,
                performanceParts: resourcePerformanceParts.performanceParts,
                entry: performanceEvent,
                color: colorForEntry(performanceEvent.initiator_type),
            }

            resourceTimings.push(next)
            maxTime = Math.max(performanceEvent.response_end || -1, maxTime)
        }
    })

    return {
        pointsInTime: pointsInTime.sort((a, b) => {
            if (a.time < b.time) {
                return -1
            }
            if (a.time > b.time) {
                return 1
            }
            return 0
        }),
        resourceTimings,
        maxTime,
        timestamp: timestamp || 'unknown',
        gridMarkers: Array.from(Array(10).keys()).map((n) => n * (maxTime / 10)),
    }
}

export const webPerformanceLogic = kea<webPerformanceLogicType>([
    path(['scenes', 'performance']),
    connect({ values: [featureFlagsLogic, ['featureFlags']] }),
    actions({
        pageViewToDisplay: (pageview: PerformancePageView | null) => ({
            pageview,
        }),
        clearDisplayedPageView: true,
        highlightPointInTime: (markerName: string | null) => ({ markerName }),
    }),
    reducers({
        highlightedPointInTime: [null as string | null, { highlightPointInTime: (_, { markerName }) => markerName }],
        pageviewEventsFailed: [
            false,
            {
                loadEventsSuccess: () => false,
                loadEventsFailure: () => true,
            },
        ],
    }),
    selectors(() => ({
        // waterfallData: [
        //     (s) => [s.pageviewEvents],
        //     (pageviewEvents) => {
        //         return forWaterfallDisplay(pageviewEvents)
        //     },
        // ],
    })),
])
