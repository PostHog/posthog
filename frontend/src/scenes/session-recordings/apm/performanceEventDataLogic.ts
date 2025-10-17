import { connect, kea, key, path, props, selectors } from 'kea'

import {
    getPerformanceEvents,
    initiatorToAssetTypeMapping,
    itemSizeInfo,
} from 'scenes/session-recordings/apm/performance-event-utils'
import { InspectorListItemBase } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import {
    SessionRecordingDataCoordinatorLogicProps,
    sessionRecordingDataCoordinatorLogic,
} from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'

import { PerformanceEvent, RecordingEventType } from '~/types'

import type { performanceEventDataLogicType } from './performanceEventDataLogicType'

export type InspectorListItemPerformance = InspectorListItemBase & {
    type: 'network'
    data: PerformanceEvent
}

export interface PerformanceEventDataLogicProps extends SessionRecordingDataCoordinatorLogicProps {
    key?: string
}

/** it's pretty quick to sort an already sorted list */
function sortPerformanceEvents(events: PerformanceEvent[]): PerformanceEvent[] {
    return events.sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))
}

/**
 * If we have paint events we should add them to the appropriate navigation event
 * this makes it easier to draw performance cards for navigation events
 */
function matchPaintEvents(performanceEvents: PerformanceEvent[]): PerformanceEvent[] {
    // NB: this relies on the input being sorted by timestamp and relies on the identity of the events to mutate them
    let lastNavigationEvent: PerformanceEvent | null = null
    for (const event of sortPerformanceEvents(performanceEvents)) {
        if (event.entry_type === 'navigation') {
            lastNavigationEvent = event
        } else if (event.entry_type === 'paint' && event.name === 'first-contentful-paint' && lastNavigationEvent) {
            lastNavigationEvent.first_contentful_paint = event.start_time
        }
    }

    return performanceEvents
}

function matchWebVitalsEvents(
    performanceEvents: PerformanceEvent[],
    webVitalsEvents: RecordingEventType[]
): PerformanceEvent[] {
    // NB: this relies on the input being sorted by timestamp and relies on the identity of the events to mutate them

    if (!webVitalsEvents.length) {
        return performanceEvents
    }

    // first we get the timestamps of each navigation event,
    // any web vitals events that occur between these timestamps
    // can be associated to the navigation event
    const navigationTimestamps: number[] = []
    for (const event of performanceEvents) {
        if (event.entry_type === 'navigation') {
            // TRICKY: this is typed as string|number but it is always number
            // TODO: fix this in the types
            navigationTimestamps.push(event.timestamp as number)
        }
    }

    let lastNavigationEvent: PerformanceEvent | null = null
    let nextTimestamp: number | null = null
    for (const event of sortPerformanceEvents(performanceEvents)) {
        if (event.entry_type === 'navigation') {
            lastNavigationEvent = event
            nextTimestamp = navigationTimestamps.find((t) => t > (event.timestamp as number)) ?? null
        } else {
            if (!lastNavigationEvent) {
                continue
            }

            for (const webVital of webVitalsEvents) {
                if (webVital.properties.$current_url !== lastNavigationEvent.name) {
                    continue
                }

                const webVitalUnixTimestamp = new Date(webVital.timestamp).valueOf()
                const isAfterLastNavigation = webVitalUnixTimestamp > (lastNavigationEvent.timestamp as number)
                const isBeforeNextNavigation = webVitalUnixTimestamp < (nextTimestamp ?? Infinity)
                if (isAfterLastNavigation && isBeforeNextNavigation) {
                    lastNavigationEvent.web_vitals = lastNavigationEvent.web_vitals || new Set()
                    lastNavigationEvent.web_vitals.add(webVital)
                }
            }
        }
    }

    return performanceEvents
}

export const performanceEventDataLogic = kea<performanceEventDataLogicType>([
    path(['scenes', 'session-recordings', 'apm', 'performanceEventDataLogic']),
    props({} as PerformanceEventDataLogicProps),
    key((props: PerformanceEventDataLogicProps) => `${props.key}-${props.sessionRecordingId}`),
    connect((props: PerformanceEventDataLogicProps) => ({
        actions: [],
        values: [sessionRecordingDataCoordinatorLogic(props), ['sessionPlayerData', 'webVitalsEvents']],
    })),
    selectors(() => ({
        allPerformanceEvents: [
            (s) => [s.sessionPlayerData, s.webVitalsEvents],
            (sessionPlayerData, webVitalsEvents): PerformanceEvent[] => {
                // TRICKY: we listen to webVitalsEventsLoading to trigger a recompute once all the data is present

                // performanceEvents used to come from the API,
                // but we decided to instead store them in the recording data
                // we gather more info than rrweb, so we mix the two back together here

                const performanceEvents = getPerformanceEvents(sessionPlayerData.snapshotsByWindowId)
                const filteredPerformanceEvents = filterUnwanted(performanceEvents)
                const deduplicatedPerformanceEvents = deduplicatePerformanceEvents(filteredPerformanceEvents)
                const sortedEvents = sortPerformanceEvents(deduplicatedPerformanceEvents)
                const withMatchedPaintEvents = matchPaintEvents(sortedEvents)
                return matchWebVitalsEvents(withMatchedPaintEvents, webVitalsEvents)
            },
        ],
        sizeBreakdown: [
            (s) => [s.allPerformanceEvents],
            (allPerformanceEvents) => {
                const breakdown: Record<string, AssetSizeInfo> = {}
                allPerformanceEvents.forEach((event) => {
                    const label = initiatorToAssetTypeMapping[event.initiator_type || 'unknown'] || 'unknown'
                    breakdown[label] = breakdown[label] || {
                        bytes: 0,
                        decodedBodySize: 0,
                        encodedBodySize: 0,
                        count: 0,
                    }
                    const sizeInfo = itemSizeInfo(event)
                    breakdown[label] = {
                        bytes: breakdown[label].bytes + (sizeInfo.bytes ?? 0),
                        decodedBodySize: breakdown[label].decodedBodySize + (sizeInfo.decodedBodySize ?? 0),
                        encodedBodySize: breakdown[label].encodedBodySize + (sizeInfo.encodedBodySize ?? 0),
                    }
                })
                return breakdown
            },
        ],
    })),
])

export interface AssetSizeInfo {
    bytes: number
    decodedBodySize: number
    encodedBodySize: number
}

function filterUnwanted(events: PerformanceEvent[]): PerformanceEvent[] {
    // the browser can provide network events that we're not interested in,
    // like a navigation to "about:blank"
    return events.filter((event) => {
        const hasNoName = !event.name?.trim().length
        const isNavigationToAbout = event.entry_type === 'navigation' && !!event.name && event.name.startsWith('about:')
        return !(hasNoName || isNavigationToAbout)
    })
}

function deduplicatePerformanceEvents(events: PerformanceEvent[]): PerformanceEvent[] {
    // we capture performance entries in the `isInitial` requests
    // which are those captured before we've wrapped fetch
    // since we're trying hard to avoid missing requests we sometimes capture the same request twice
    // once isInitial and once is the actual fetch
    // the actual fetch will have more data, so we can discard the isInitial
    const seen = new Set<string>()
    return events
        .reverse()
        .filter((event) => {
            // the timestamp isn't always exactly the same e.g. they could be one or two milliseconds apart
            // just because of processing time.
            // So we'll round down to the nearest 10ms
            const reducedGranularityTimestamp =
                typeof event.timestamp === 'number' ? Math.floor(event.timestamp / 10) * 10 : event.timestamp
            const key = `${event.entry_type}-${event.name}-${reducedGranularityTimestamp}-${event.window_id}`
            // we only want to drop is_initial events
            if (seen.has(key) && event.is_initial) {
                return false
            }
            seen.add(key)
            return true
        })
        .reverse()
}
