import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { PlayerPosition, SessionRecordingPlayerTab } from '~/types'
import List, { RenderedRows } from 'react-virtualized/dist/es/List'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { eventsListLogic } from 'scenes/session-recordings/player/inspector/eventsListLogic'
import { ceilMsToClosestSecond, clamp, findLastIndex, floorMsToClosestSecond } from 'lib/utils'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/inspector/consoleLogsListLogic'
import type { listLogicType } from './listLogicType'

export enum RowStatus {
    Warning = 'warning',
    Error = 'error',
    Information = 'information',
    Match = 'match',
}
export const DEFAULT_ROW_HEIGHT = 40 + 4 // Default height + padding
export const DEFAULT_EXPANDED_ROW_HEIGHT = 360 + 4 // Default expanded height + padding
export const OVERSCANNED_ROW_COUNT = 25
const DEFAULT_SCROLLING_RESET_TIME_INTERVAL = 150 * 5 // https://github.com/bvaughn/react-virtualized/blob/abe0530a512639c042e74009fbf647abdb52d661/source/Grid/Grid.js#L42

export interface ListLogicProps extends SessionRecordingPlayerLogicProps {
    tab: SessionRecordingPlayerTab
}

// See sharedListLogic for logic that is shared across recording tabs
export const listLogic = kea<listLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'listLogic', key]),
    props({} as ListLogicProps),
    key((props: ListLogicProps) => `${props.playerKey}-${props.sessionRecordingId}-${props.tab}`),
    connect(({ sessionRecordingId, playerKey }: ListLogicProps) => ({
        logic: [eventUsageLogic],
        actions: [sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }), ['seek']],
        values: [
            sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }),
            ['currentPlayerTime'],
            eventsListLogic({ sessionRecordingId, playerKey }),
            ['eventListData'],
            consoleLogsListLogic({ sessionRecordingId, playerKey }),
            ['consoleListData'],
        ],
    })),
    actions(() => ({
        setList: (list: List) => ({ list }),
        setRenderedRows: (renderMeta: RenderedRows) => ({ renderMeta }),
        enablePositionFinder: true,
        disablePositionFinder: true,
        scrollTo: (rowIndex?: number) => ({ rowIndex }),
        handleRowClick: (playerPosition: PlayerPosition) => ({ playerPosition }),
        expandRow: (rowIndex?: number) => ({ rowIndex }),
        collapseRow: (rowIndex?: number) => ({ rowIndex }),
    })),
    reducers(() => ({
        renderedRows: [
            {
                startIndex: 0,
                stopIndex: 0,
                overscanStartIndex: 0,
                overscanStopIndex: 0,
            } as RenderedRows,
            {
                setRenderedRows: (_, { renderMeta }) => renderMeta,
            },
        ],
        expandedRows: [
            new Set<number>(),
            {
                expandRow: (state, { rowIndex }) =>
                    rowIndex === undefined ? state : new Set([...Array.from(state), rowIndex]),
                collapseRow: (state, { rowIndex }) =>
                    rowIndex === undefined ? state : new Set(Array.from(state).filter((index) => index !== rowIndex)),
            },
        ],
        list: [
            null as List | null,
            {
                setList: (_, { list }) => list,
            },
        ],
        shouldHidePositionFinder: [
            false,
            {
                scrollTo: () => true,
                enablePositionFinder: () => false,
                disablePositionFinder: () => true,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        scrollTo: async ({ rowIndex: _rowIndex }, breakpoint) => {
            const rowIndex = _rowIndex ?? values.currentIndices.startIndex
            if (values.list) {
                values.list.scrollToPosition(values.list.getOffsetForRow({ alignment: 'center', index: rowIndex }))
                eventUsageLogic.actions.reportRecordingScrollTo(rowIndex)
            }
            // Enable position finder so that it can become visible again. Turning it off at scroll start
            // makes sure that it stays hidden for the duration of the auto scroll.
            await breakpoint(DEFAULT_SCROLLING_RESET_TIME_INTERVAL)
            actions.enablePositionFinder()
        },
        handleRowClick: ({ playerPosition }) => {
            if (playerPosition) {
                // NOTE: Seek to 1 second before the event to make sure the event is visible
                actions.seek({
                    ...playerPosition,
                    time: Math.max(0, playerPosition.time - 1000),
                })
            }
        },
    })),
    selectors(({ props }) => ({
        data: [
            (selectors) => [selectors.eventListData, selectors.consoleListData],
            (eventListData, consoleListData): Record<string, any>[] =>
                props.tab === SessionRecordingPlayerTab.CONSOLE ? consoleListData : eventListData,
        ],
        currentStartIndex: [
            (selectors) => [selectors.data, selectors.currentPlayerTime],
            (data, currentPlayerTime): number => {
                return data.findIndex((e) => (e.playerTime ?? 0) >= ceilMsToClosestSecond(currentPlayerTime ?? 0))
            },
        ],
        currentTimeRange: [
            (selectors) => [selectors.currentStartIndex, selectors.data, selectors.currentPlayerTime],
            (startIndex, data, currentPlayerTime) => {
                if (data.length < 1) {
                    return { start: 0, end: 0 }
                }
                const end = Math.max(ceilMsToClosestSecond(currentPlayerTime ?? 0), 1000)
                const start = floorMsToClosestSecond(
                    data[clamp(startIndex === -1 ? data.length - 1 : startIndex - 1, 0, data.length - 1)].playerTime ??
                        0
                )

                return { start, end }
            },
        ],
        isCurrent: [
            (selectors) => [selectors.currentTimeRange, selectors.data],
            (indices, data) => (index: number) =>
                (data?.[index]?.playerTime ?? 0) >= indices.start && (data?.[index]?.playerTime ?? 0) < indices.end,
        ],
        currentIndices: [
            (selectors) => [selectors.data, selectors.isCurrent],
            (data, isCurrent) => ({
                startIndex: clamp(
                    data.findIndex((_, i) => isCurrent(i)),
                    0,
                    data.length - 1
                ),
                stopIndex: clamp(
                    findLastIndex(data, (_, i) => isCurrent(i)),
                    0,
                    data.length - 1
                ),
            }),
        ],
        isRowIndexRendered: [
            (selectors) => [selectors.renderedRows],
            (renderedRows) => (index: number) =>
                index >= renderedRows.overscanStartIndex && index <= renderedRows.overscanStopIndex,
        ],
        showPositionFinder: [
            (selectors) => [selectors.renderedRows, selectors.currentIndices, selectors.shouldHidePositionFinder],
            (visibleRange, currentIndices, shouldHidePositionFinder) => {
                // Only show finder if there's no overlap of view range and current events range
                return (
                    !shouldHidePositionFinder &&
                    (visibleRange.stopIndex < currentIndices.startIndex ||
                        visibleRange.startIndex > currentIndices.stopIndex)
                )
            },
        ],
        isDirectionUp: [
            (selectors) => [selectors.renderedRows, selectors.currentIndices],
            (visibleRange, currentIndices) => {
                // Where are we relative to the current event
                return visibleRange.startIndex > currentIndices.stopIndex
            },
        ],
    })),
])
