import './PlayerList.scss'
import { ReactElement, useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { SessionRecordingPlayerTab } from '~/types'
import {
    DEFAULT_EXPANDED_ROW_HEIGHT,
    DEFAULT_ROW_HEIGHT,
    listLogic,
    OVERSCANNED_ROW_COUNT,
    RowStatus,
} from 'scenes/session-recordings/player/list/listLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { List } from 'react-virtualized/dist/es/List'
import { Empty } from 'antd'
import clsx from 'clsx'
import { ArrowDownOutlined, ArrowUpOutlined, CloseOutlined } from '@ant-design/icons'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { ExpandableConfig } from 'lib/components/LemonTable'
import { ListRowOptions, PlayerListRow } from 'scenes/session-recordings/player/list/PlayerListRow'
import { getRowExpandedState } from 'scenes/session-recordings/player/playerUtils'
import { teamLogic } from 'scenes/teamLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { openSessionRecordingSettingsDialog } from 'scenes/session-recordings/settings/SessionRecordingSettings'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'

interface RowConfig<T extends Record<string, any>> {
    /** Class to append to each row. */
    className?: string | ((record: T) => string | null)
    /** Status of each row. Defaults no status */
    status?: RowStatus | ((record: T) => RowStatus | null)
    /** Callback to render main content on left side of row */
    content?: ReactElement | ((record: T, index: number, expanded: boolean) => ReactElement | null)
    /** Callback to render main content on right side of row */
    sideContent?: ReactElement | ((record: T, index: number, expanded: boolean) => ReactElement | null)
    /** Side menu options for each row in the list **/
    options?: ListRowOptions<T> | ((record: T, index: number) => ListRowOptions<T>)
}

export interface PlayerListExpandableConfig<T extends Record<string, any>> extends ExpandableConfig<T> {
    /** If specified, replace the preview content in the row with custom render */
    expandedPreviewContentRender?: (record: T, recordIndex: number) => any
}

export interface PlayerListProps<T extends Record<string, any>> extends SessionRecordingPlayerLogicProps {
    tab: SessionRecordingPlayerTab
    expandable?: PlayerListExpandableConfig<T>
    row?: RowConfig<T>
}

export function PlayerList<T extends Record<string, any>>({
    tab,
    expandable,
    row,
    sessionRecordingId,
    playerKey,
}: PlayerListProps<T>): JSX.Element {
    const listRef = useRef<List>(null)
    const logic = listLogic({ tab, sessionRecordingId, playerKey })
    const { data, showPositionFinder, isCurrent, isDirectionUp, expandedRows } = useValues(logic)
    const { setRenderedRows, setList, scrollTo, disablePositionFinder, handleRowClick, expandRow, collapseRow } =
        useActions(logic)
    const { sessionEventsDataLoading, sessionPlayerMetaDataLoading, windowIds } = useValues(
        sessionRecordingDataLogic({ sessionRecordingId, playerKey })
    )
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    useEffect(() => {
        if (listRef?.current) {
            setList(listRef.current)
        }
    }, [listRef.current, tab])

    return (
        <div className="PlayerList">
            {!data.length && (sessionEventsDataLoading || sessionPlayerMetaDataLoading) ? (
                <SpinnerOverlay />
            ) : (
                <>
                    {listRef?.current && (
                        <div className={clsx('PlayerList__position-finder', { visible: showPositionFinder })}>
                            <div
                                className="flex justify-center items-center grow left"
                                onClick={() => {
                                    scrollTo()
                                }}
                            >
                                {isDirectionUp ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                                Jump to current time
                            </div>
                            <div
                                className="flex justify-center items-center right"
                                onClick={() => {
                                    disablePositionFinder()
                                }}
                            >
                                <CloseOutlined />
                            </div>
                        </div>
                    )}
                    <AutoSizer>
                        {({ height, width }: { height: number; width: number }) => {
                            return (
                                <List
                                    ref={listRef}
                                    className="player-list-virtual"
                                    height={height}
                                    width={width}
                                    onRowsRendered={setRenderedRows}
                                    noRowsRenderer={() =>
                                        // TODO @benjackwhite - add upsell for performance too
                                        tab === SessionRecordingPlayerTab.CONSOLE &&
                                        !currentTeam?.capture_console_log_opt_in ? (
                                            <div className="flex flex-col items-center h-full w-full pt-16 px-4 bg-white">
                                                <h4 className="text-xl font-medium">Introducing Console Logs</h4>
                                                <p className="text-muted">
                                                    Capture all console logs that are fired as part of a recording.
                                                </p>
                                                <LemonButton
                                                    className="mb-2"
                                                    onClick={() => {
                                                        updateCurrentTeam({ capture_console_log_opt_in: true })
                                                    }}
                                                    type="primary"
                                                >
                                                    Turn on console log capture for future recordings
                                                </LemonButton>
                                                <LemonButton
                                                    onClick={() => openSessionRecordingSettingsDialog()}
                                                    targetBlank
                                                >
                                                    Configure in settings
                                                </LemonButton>
                                            </div>
                                        ) : (
                                            <div className="flex justify-center h-full pt-20">
                                                <Empty
                                                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                                                    description={`No ${
                                                        tab === SessionRecordingPlayerTab.EVENTS
                                                            ? 'events'
                                                            : 'console logs'
                                                    } captured in this recording.`}
                                                />
                                            </div>
                                        )
                                    }
                                    overscanRowCount={OVERSCANNED_ROW_COUNT} // in case autoscrolling scrolls faster than we render.
                                    overscanIndicesGetter={({
                                        cellCount,
                                        overscanCellsCount,
                                        startIndex,
                                        stopIndex,
                                    }) => {
                                        const under = Math.floor(overscanCellsCount / 2)
                                        const over = overscanCellsCount - under
                                        return {
                                            overscanStartIndex: Math.max(0, startIndex - under),
                                            overscanStopIndex: Math.min(cellCount - 1, stopIndex + over),
                                        }
                                    }}
                                    rowCount={data.length}
                                    rowRenderer={({ index, style, key }) => {
                                        const record = data[index] as T
                                        const expandedDetermined = getRowExpandedState(
                                            record,
                                            index,
                                            expandable,
                                            expandedRows.has(index)
                                        )
                                        const rowKeyDetermined = key ?? index
                                        const rowClassNameDetermined =
                                            typeof row?.className === 'function'
                                                ? row.className(record)
                                                : row?.className
                                        const rowStatusDetermined =
                                            typeof row?.status === 'function' ? row.status(record) : row?.status
                                        const rowCurrentDetermined = isCurrent(index)
                                        const rowContentDetermined =
                                            typeof row?.content === 'function'
                                                ? row.content(record, index, expandedDetermined)
                                                : row?.content
                                        const rowSideContentDetermined =
                                            typeof row?.sideContent === 'function'
                                                ? row.sideContent(record, index, expandedDetermined)
                                                : row?.sideContent
                                        const optionsDetermined =
                                            typeof row?.options === 'function'
                                                ? row.options(record, index)
                                                : row?.options

                                        return (
                                            <PlayerListRow
                                                key={`PlayerList-Row-${rowKeyDetermined}`}
                                                record={record}
                                                recordIndex={index}
                                                keyDetermined={rowKeyDetermined}
                                                classNameDetermined={rowClassNameDetermined}
                                                statusDetermined={rowStatusDetermined}
                                                currentDetermined={rowCurrentDetermined}
                                                style={style}
                                                expandable={
                                                    expandable
                                                        ? {
                                                              ...expandable,
                                                              onRowExpand: (record, index) => {
                                                                  expandable?.onRowExpand?.(record, index)
                                                                  expandRow(index)
                                                                  listRef?.current?.recomputeRowHeights(index)
                                                              },
                                                              onRowCollapse: (_, index) => {
                                                                  expandable?.onRowCollapse?.(record, index)
                                                                  collapseRow(index)
                                                                  listRef?.current?.recomputeRowHeights(index)
                                                              },
                                                          }
                                                        : undefined
                                                }
                                                contentDetermined={rowContentDetermined}
                                                sideContentDetermined={rowSideContentDetermined}
                                                onClick={(record) => {
                                                    handleRowClick(record.playerPosition)
                                                }}
                                                optionsDetermined={optionsDetermined ?? []}
                                                expandedDetermined={expandedDetermined}
                                                loading={sessionEventsDataLoading}
                                                windowNumber={
                                                    windowIds.length > 1
                                                        ? windowIds.indexOf(record.playerPosition.windowId) + 1 ||
                                                          undefined
                                                        : undefined
                                                }
                                            />
                                        )
                                    }}
                                    rowHeight={({ index }) => {
                                        const record = data[index] as T
                                        if (getRowExpandedState(record, index, expandable, expandedRows.has(index))) {
                                            return DEFAULT_EXPANDED_ROW_HEIGHT
                                        }

                                        return DEFAULT_ROW_HEIGHT
                                    }}
                                />
                            )
                        }}
                    </AutoSizer>
                </>
            )}
        </div>
    )
}
