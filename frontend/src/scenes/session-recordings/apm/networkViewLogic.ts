import { afterMount, connect, kea, path, props, selectors } from 'kea'
import { performanceEventDataLogic } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import {
    sessionRecordingDataLogic,
    SessionRecordingDataLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { PerformanceEvent } from '~/types'

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
    afterMount(({ actions }) => {
        actions.maybeLoadRecordingMeta()
        actions.loadSnapshots()
    }),
    selectors({
        isLoading: [
            (s) => [s.snapshotsLoading, s.sessionPlayerMetaDataLoading],
            (snapshotsLoading, sessionPlayerMetaDataLoading) => snapshotsLoading || sessionPlayerMetaDataLoading,
        ],
        pageViews: [
            (s) => [s.allPerformanceEvents],
            (allPerformanceEvents: PerformanceEvent[]) => {
                // ignore events before the first navigation event
                // then we take each navigation events URL as a key to an object
                // the object value is an error of performance events
                // including the navigation event and any other events between it and the next navigation event

                const pages = {}
                let lastNavigationURL: string | null = null

                for (const perfEvent of allPerformanceEvents) {
                    const hasAnyNavigation = Object.keys(pages).length
                    const eventType = perfEvent.entry_type
                    if (!hasAnyNavigation && eventType !== 'navigation') {
                        continue
                    }
                    if (eventType === 'navigation') {
                        if (!perfEvent.name) {
                            continue
                        }
                        pages[perfEvent.name] = [perfEvent]
                        lastNavigationURL = perfEvent.name
                    } else if (lastNavigationURL) {
                        pages[lastNavigationURL].push(perfEvent)
                    }
                }

                return pages
            },
        ],
    }),
])
