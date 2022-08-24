import './PlayerList.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { SessionRecordingTab } from '~/types'
import {
    DEFAULT_ROW_HEIGHT,
    listLogic,
    OVERSCANNED_ROW_COUNT,
    RowStatus,
} from 'scenes/session-recordings/player/list/listLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { List } from 'react-virtualized/dist/es/List'
import { Empty } from 'antd'
import clsx from 'clsx'
import { ArrowDownOutlined, ArrowUpOutlined, CloseOutlined } from '@ant-design/icons'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { ExpandableConfig } from 'lib/components/LemonTable'
import { PlayerListRow } from 'scenes/session-recordings/player/list/PlayerListRow'

interface RowConfig<T extends Record<string, any>> {
    /** Class to append to each row. */
    className?: string | ((record: T) => string | null)
    /** Status of each row. Defaults no status */
    status?: RowStatus | ((record: T) => RowStatus | null)
    /** Callback to render main content on left side of row */
    content?: JSX.Element | ((record: T) => JSX.Element | null)
    /** Callback to render main content on right side of row */
    sideContent?: JSX.Element | ((record: T) => JSX.Element | null)
}

export interface PlayerListProps<T> {
    tab: SessionRecordingTab
    expandable?: ExpandableConfig<T>
    row?: RowConfig<T>
}

export function PlayerList<T extends Record<string, any>>({ tab, expandable, row }: PlayerListProps<T>): JSX.Element {
    const listRef = useRef<List>(null)
    const logic = listLogic({ tab })
    const { data, showPositionFinder, isCurrent, isDirectionUp } = useValues(logic)
    const { setRenderedRows, setList, scrollTo, disablePositionFinder, handleRowClick } = useActions(logic)
    const { sessionEventsDataLoading } = useValues(sessionRecordingLogic)

    useEffect(() => {
        if (listRef?.current) {
            setList(listRef.current)
        }
    }, [listRef.current])

    console.log('LISTDATA', data)

    return (
        <div className="PlayerList">
            {sessionEventsDataLoading ? (
                <SpinnerOverlay />
            ) : (
                <>
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
                    <AutoSizer>
                        {({ height, width }: { height: number; width: number }) => {
                            return (
                                <List
                                    ref={listRef}
                                    className="event-list-virtual"
                                    height={height}
                                    width={width}
                                    onRowsRendered={setRenderedRows}
                                    noRowsRenderer={() => (
                                        <div className="event-list-empty-container">
                                            <Empty
                                                image={Empty.PRESENTED_IMAGE_SIMPLE}
                                                description="No events fired in this recording."
                                            />
                                        </div>
                                    )}
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
                                        const rowKeyDetermined = key ?? index
                                        const rowClassNameDetermined =
                                            typeof row?.className === 'function'
                                                ? row.className(record)
                                                : row?.className
                                        const rowStatusDetermined =
                                            typeof row?.status === 'function' ? row.status(record) : row?.status
                                        const rowCurrentDetermined = isCurrent(index)
                                        const rowContentDetermined =
                                            typeof row?.content === 'function' ? row.content(record) : row?.content
                                        const rowSideContentDetermined =
                                            typeof row?.sideContent === 'function'
                                                ? row.sideContent(record)
                                                : row?.sideContent

                                        return (
                                            <PlayerListRow
                                                key={`PlayerList-Row-${rowKeyDetermined}`}
                                                record={record}
                                                recordIndex={index}
                                                keyDetermined={rowKeyDetermined}
                                                classNameDetermined={rowClassNameDetermined}
                                                statusDetermined={rowStatusDetermined}
                                                currentDetermined={rowCurrentDetermined}
                                                style={{ ...style, zIndex: data.length - index }}
                                                expandable={expandable}
                                                contentDetermined={rowContentDetermined}
                                                sideContentDetermined={rowSideContentDetermined}
                                                onClick={(record) => {
                                                    handleRowClick(record.playerPosition)
                                                }}
                                            />
                                        )
                                    }}
                                    rowHeight={DEFAULT_ROW_HEIGHT}
                                />
                            )
                        }}
                    </AutoSizer>
                </>
            )}
        </div>
    )
}
