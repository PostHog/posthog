import { connect, kea, key, path, props, selectors } from 'kea'
import { matchNetworkEvents } from 'scenes/session-recordings/player/inspector/performance-event-utils'
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

                return deduplicatePerformanceEvents(
                    filterUnwanted(matchNetworkEvents(sessionPlayerData.snapshotsByWindowId))
                ).sort((a, b) => (a.timestamp.valueOf() > b.timestamp.valueOf() ? 1 : -1))
            },
        ],
    })),
])

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
