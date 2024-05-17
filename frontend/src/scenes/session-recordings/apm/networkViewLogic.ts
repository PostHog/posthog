import { actions, afterMount, connect, kea, path, props, reducers, selectors } from 'kea'
import { performanceEventDataLogic } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import {
    sessionRecordingDataLogic,
    SessionRecordingDataLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { PerformanceEvent, PersonType } from '~/types'

import type { networkViewLogicType } from './networkViewLogicType'

export interface NetworkViewLogicProps extends SessionRecordingDataLogicProps {}

export const networkViewLogic = kea<networkViewLogicType>([
    path(['scenes', 'session-recordings', 'apm', 'networkViewLogic']),
    props({} as NetworkViewLogicProps),
    connect((props: NetworkViewLogicProps) => ({
        values: [
            sessionRecordingDataLogic(props),
            ['sessionPlayerData', 'sessionPlayerMetaData', 'snapshotsLoading', 'sessionPlayerMetaDataLoading'],
            performanceEventDataLogic({ key: props.sessionRecordingId, sessionRecordingId: props.sessionRecordingId }),
            ['allPerformanceEvents'],
        ],
        actions: [sessionRecordingDataLogic(props), ['loadSnapshots', 'maybeLoadRecordingMeta']],
    })),
    actions({
        nextPage: () => true,
        prevPage: () => true,
    }),
    reducers({
        page: [
            0,
            {
                nextPage: (state) => state + 1,
                prevPage: (state) => Math.max(0, state - 1),
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.maybeLoadRecordingMeta()
        actions.loadSnapshots()
    }),
    selectors({
        sessionPerson: [
            (s) => [s.sessionPlayerData],
            (playerData): PersonType | null => {
                return playerData?.person ?? null
            },
        ],
        isLoading: [
            (s) => [s.snapshotsLoading, s.sessionPlayerMetaDataLoading],
            (snapshotsLoading, sessionPlayerMetaDataLoading) => snapshotsLoading || sessionPlayerMetaDataLoading,
        ],
        pageViews: [
            (s) => [s.allPerformanceEvents],
            (allPerformanceEvents: PerformanceEvent[]) => {
                // ignore events before the first navigation event
                // then we create an array of performance events for each page
                // and store them in an array
                const pages: PerformanceEvent[][] = []

                for (const perfEvent of allPerformanceEvents) {
                    const hasAnyNavigation = Object.keys(pages).length
                    const eventType = perfEvent.entry_type
                    if (!hasAnyNavigation && eventType !== 'navigation') {
                        continue
                    }
                    if (eventType === 'navigation') {
                        pages.push([perfEvent])
                    } else {
                        pages[pages.length - 1].push(perfEvent)
                    }
                }

                return pages
            },
        ],
        pageCount: [(s) => [s.pageViews], (pageViews) => pageViews.length],
        currentPage: [
            (s) => [s.pageViews, s.page],
            (pageViews, page) => {
                return pageViews[page] || []
            },
        ],
    }),
])
