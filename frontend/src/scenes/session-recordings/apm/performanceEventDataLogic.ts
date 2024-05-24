import { connect, kea, key, path, props, selectors } from 'kea'
import {
    initiatorToAssetTypeMapping,
    itemSizeInfo,
    matchNetworkEvents,
} from 'scenes/session-recordings/apm/performance-event-utils'
import { InspectorListItemBase } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    sessionRecordingDataLogic,
    SessionRecordingDataLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { PerformanceEvent, SessionRecordingPlayerTab } from '~/types'

import type { performanceEventDataLogicType } from './performanceEventDataLogicType'

export type InspectorListItemPerformance = InspectorListItemBase & {
    type: SessionRecordingPlayerTab.NETWORK
    data: PerformanceEvent
}

export interface PerformanceEventDataLogicProps extends SessionRecordingDataLogicProps {
    key?: string
}

/**
 * If we have paint events we should add them to the appropriate navigation event
 * this makes it easier to draw performance cards for navigation events
 */
function matchPaintEvents(performanceEvents: PerformanceEvent[]): PerformanceEvent[] {
    // KLUDGE: this assumes that the input is sorted by timestamp and relies on the identity of the events to mutate them
    let lastNavigationEvent: PerformanceEvent | null = null
    for (const event of performanceEvents) {
        if (event.entry_type === 'navigation') {
            lastNavigationEvent = event
        } else if (event.entry_type === 'paint' && event.name === 'first-contentful-paint' && lastNavigationEvent) {
            lastNavigationEvent.first_contentful_paint = event.start_time
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
        values: [
            playerSettingsLogic,
            ['showOnlyMatching', 'tab', 'miniFiltersByKey', 'searchQuery'],
            sessionRecordingDataLogic(props),
            [
                'sessionPlayerData',
                'sessionPlayerMetaDataLoading',
                'snapshotsLoading',
                'sessionEventsData',
                'sessionEventsDataLoading',
                'windowIds',
                'start',
                'end',
                'durationMs',
            ],
        ],
    })),
    selectors(() => ({
        allPerformanceEvents: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData): PerformanceEvent[] => {
                // performanceEvents used to come from the API,
                // but we decided to instead store them in the recording data
                // we gather more info than rrweb, so we mix the two back together here

                return matchPaintEvents(
                    deduplicatePerformanceEvents(
                        filterUnwanted(matchNetworkEvents(sessionPlayerData.snapshotsByWindowId))
                    ).sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))
                )
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
        return !(event.entry_type === 'navigation' && event.name && event.name.startsWith('about:'))
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
            const key = `${event.entry_type}-${event.name}-${event.timestamp}-${event.window_id}`
            // we only want to drop is_initial events
            if (seen.has(key) && event.is_initial) {
                return false
            }
            seen.add(key)
            return true
        })
        .reverse()
}
