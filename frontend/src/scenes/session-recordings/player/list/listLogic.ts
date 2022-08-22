import { actions, connect, kea, key, listeners, Logic, path, props, reducers, selectors } from 'kea'
import { PlayerPosition, RecordingTimeMixinType, SessionRecordingTab } from '~/types'
import List, { RenderedRows } from 'react-virtualized/dist/es/List'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    DEFAULT_SCROLLING_RESET_TIME_INTERVAL,
    eventsListLogic,
} from 'scenes/session-recordings/player/list/eventsListLogic'
import { ceilMsToClosestSecond, clamp, findLastIndex, floorMsToClosestSecond } from 'lib/utils'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/list/consoleLogsListLogic'

import type { listLogicType } from './listLogicType'

export const TAB_TO_LOGIC: Record<SessionRecordingTab, Logic> = {
    [SessionRecordingTab.EVENTS]: eventsListLogic,
    [SessionRecordingTab.CONSOLE]: consoleLogsListLogic,
}

export interface ListLogicProps {
    tab: SessionRecordingTab
}

export const listLogic = kea<listLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'listLogic', key]),
    props({} as ListLogicProps),
    key(({ tab }) => tab),
    connect(() => ({
        logic: [eventUsageLogic],
        actions: [sessionRecordingPlayerLogic, ['seek']],
        values: [sessionRecordingPlayerLogic, ['currentPlayerTime']],
    })),
    actions(() => ({
        setList: (list: List) => ({ list }),
        setRenderedRows: (renderMeta: RenderedRows) => ({ renderMeta }),
        enablePositionFinder: true,
        disablePositionFinder: true,
        scrollTo: (rowIndex?: number) => ({ rowIndex }),
        handleRowClick: (playerPosition: PlayerPosition) => ({ playerPosition }),
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
                actions.seek(playerPosition)
            }
        },
    })),
    selectors(() => ({
        data: [
            () => [(_, props) => props.tab],
            (tab): RecordingTimeMixinType[] => {
                return TAB_TO_LOGIC[tab]?.findMounted?.values?.data
            },
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
        currentBoxSizeAndPosition: [
            (selectors) => [selectors.currentIndices, selectors.list],
            (indices, list) => {
                if (
                    !list ||
                    !list.Grid ||
                    indices.startIndex >= list.Grid.props.rowCount ||
                    indices.stopIndex > list.Grid.props.rowCount ||
                    (indices.startIndex < 1 && indices.stopIndex < 1) ||
                    indices.stopIndex < indices.startIndex
                ) {
                    return {
                        top: 0,
                        height: 0,
                    }
                }

                const gridState = list.Grid.state as any
                const top = gridState.instanceProps.rowSizeAndPositionManager.getSizeAndPositionOfCell(
                    indices.startIndex
                ).offset
                const lastDatumSize = gridState.instanceProps.rowSizeAndPositionManager.getSizeAndPositionOfCell(
                    indices.stopIndex
                )
                return {
                    top,
                    height: lastDatumSize.offset + lastDatumSize.size - top,
                }
            },
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
