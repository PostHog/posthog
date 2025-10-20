import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'
import { humanFriendlyMilliseconds } from 'lib/utils'
import { performanceEventDataLogic } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import { percentagesWithinEventRange } from 'scenes/session-recordings/apm/waterfall/TimingBar'
import {
    SessionRecordingDataCoordinatorLogicProps,
    sessionRecordingDataCoordinatorLogic,
} from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'

import { PerformanceEvent } from '~/types'

import type { networkViewLogicType } from './networkViewLogicType'

export interface NetworkViewLogicProps extends SessionRecordingDataCoordinatorLogicProps {}

export const networkViewLogic = kea<networkViewLogicType>([
    path(['scenes', 'session-recordings', 'apm', 'networkViewLogic']),
    key((props) => `network-view-${props.sessionRecordingId}`),
    props({} as NetworkViewLogicProps),
    connect((props: NetworkViewLogicProps) => ({
        values: [
            sessionRecordingDataCoordinatorLogic(props),
            ['sessionPlayerData', 'sessionPlayerMetaData', 'snapshotsLoading', 'sessionPlayerMetaDataLoading', 'start'],
            performanceEventDataLogic({ key: props.sessionRecordingId, sessionRecordingId: props.sessionRecordingId }),
            ['allPerformanceEvents', 'sizeBreakdown'],
        ],
        actions: [sessionRecordingDataCoordinatorLogic(props), ['loadSnapshots', 'maybeLoadRecordingMeta']],
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
        isLoading: [
            (s) => [s.snapshotsLoading, s.sessionPlayerMetaDataLoading],
            (snapshotsLoading, sessionPlayerMetaDataLoading) => snapshotsLoading || sessionPlayerMetaDataLoading,
        ],
        pageViews: [
            (s) => [s.allPerformanceEvents, s.start],
            (
                allPerformanceEvents: PerformanceEvent[],
                start: Dayjs
            ): (PerformanceEvent & { timeInRecording: number })[][] => {
                // ignore events before the first navigation event
                // then we create an array of performance events for each page
                // and store them in an array
                const pages: (PerformanceEvent & { timeInRecording: number })[][] = []

                for (const perfEvent of allPerformanceEvents) {
                    const hasAnyNavigation = Object.keys(pages).length
                    const eventType = perfEvent.entry_type
                    if (!hasAnyNavigation && eventType !== 'navigation') {
                        continue
                    }
                    const timedEvent = {
                        ...perfEvent,
                        timeInRecording: dayjs(perfEvent.timestamp).valueOf() - start?.valueOf(),
                    }
                    if (eventType === 'navigation') {
                        pages.push([timedEvent])
                    } else {
                        pages[pages.length - 1].push(timedEvent)
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
        navigationItem: [
            (s) => [s.currentPage],
            (currentPage) => {
                if (currentPage.length) {
                    return currentPage[0]
                }
                return null
            },
        ],
        finalItem: [
            (s) => [s.currentPage],
            (currentPage) => {
                if (currentPage.length) {
                    return currentPage[currentPage.length - 1]
                }
                return null
            },
        ],
        formattedDurationFor: [
            () => [],
            () => {
                return (item: PerformanceEvent) => {
                    let formattedDuration: string | undefined
                    const itemStart = item.start_time
                    const itemEnd = item.load_event_end ? item.load_event_end : item.response_end
                    if (itemStart !== undefined && itemEnd !== undefined) {
                        const itemDuration = itemEnd - itemStart
                        formattedDuration = humanFriendlyMilliseconds(itemDuration)
                    } else {
                        formattedDuration = ''
                    }

                    return formattedDuration
                }
            },
        ],
        positionPercentagesFor: [
            (s) => [s.navigationItem, s.finalItem],
            (navigationItem, finalItem) => {
                return (item: PerformanceEvent) => {
                    if (!navigationItem || !finalItem) {
                        return
                    }

                    const rangeStart = navigationItem.start_time
                    const rangeEnd = finalItem.load_event_end ? finalItem.load_event_end : finalItem.response_end

                    const itemStart = item.start_time
                    const itemEnd = item.load_event_end ? item.load_event_end : item.response_end

                    if (
                        itemStart === undefined ||
                        itemEnd === undefined ||
                        rangeStart === undefined ||
                        rangeEnd === undefined
                    ) {
                        return null
                    }

                    const percentages = percentagesWithinEventRange({
                        rangeStart,
                        rangeEnd,
                        partStart: itemStart,
                        partEnd: itemEnd,
                    })
                    const startPercentage = percentages.startPercentage
                    const widthPercentage = percentages.widthPercentage
                    return { startPercentage, widthPercentage }
                }
            },
        ],
        hasPageViews: [(s) => [s.pageCount], (pageCount) => pageCount > 0],
    }),
])
