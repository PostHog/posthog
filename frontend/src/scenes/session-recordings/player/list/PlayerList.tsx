import './PlayerList.scss'
import React, { ReactNode, useCallback, useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { SessionRecordingTab } from '~/types'
import { DEFAULT_ROW_HEIGHT, listLogic, OVERSCANNED_ROW_COUNT } from 'scenes/session-recordings/player/list/listLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'
import { Empty } from 'antd'
import clsx from 'clsx'
import { ArrowDownOutlined, ArrowUpOutlined, CloseOutlined } from '@ant-design/icons'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { IconEllipsis, IconUnfoldMore } from 'lib/components/icons'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { ExpandableConfig } from 'lib/components/LemonTable'

export interface PlayerListProps<T> {
    tab: SessionRecordingTab
    expandable?: ExpandableConfig<T>
    renderContent?: (record: T) => ReactNode
    renderSideContent?: (record: T) => ReactNode
}

export function PlayerList<T extends Record<string, any>>({ tab }: PlayerListProps<T>): JSX.Element {
    const listRef = useRef<List>(null)
    const logic = listLogic({ tab })
    const { data, currentBoxSizeAndPosition, showPositionFinder, isCurrent, isDirectionUp, renderedRows } =
        useValues(logic)
    const { setRenderedRows, setList, scrollTo, disablePositionFinder, handleRowClick } = useActions(logic)
    const { sessionEventsDataLoading } = useValues(sessionRecordingLogic)

    useEffect(() => {
        if (listRef?.current) {
            setList(listRef.current)
        }
    }, [listRef.current])

    console.log('LISTDATA', data)

    const rowRenderer = useCallback(
        function _rowRenderer({ index, style, key }: ListRowProps): JSX.Element {
            const datum = data[index]
            const _isCurrent = isCurrent(index)

            return (
                <div
                    key={key}
                    className={clsx('PlayerList__item', { 'PlayerList__item--current': _isCurrent }, 'bg-transparent')}
                    style={{ ...style, zIndex: data.length - index }}
                    onClick={() => {
                        datum.playerPosition && handleRowClick(datum.playerPosition)
                    }}
                    data-tooltip="recording-player-list"
                >
                    <div className="h-full rounded flex flex-row items-center justify-between bg-light border border-border px-2">
                        <div className="flex flex-row grow gap-1 items-center">
                            <LemonButton icon={<IconUnfoldMore />} size="small" status="muted" />
                            <div>
                                <IconWindow value="1" className="text-muted" />
                            </div>
                            Content goes here
                        </div>
                        <div className="flex flex-row gap-3 items-center">
                            Right aligned content goes here
                            <div className="text-xs">{datum.colonTimestamp}</div>
                            <LemonButtonWithPopup
                                data-attr="player-list-item-menu"
                                id="player-list-item-menu"
                                icon={<IconEllipsis />}
                                size="small"
                                status="muted"
                                popup={{
                                    placement: 'bottom-end',
                                    overlay: (
                                        <>
                                            <LemonButton fullWidth status="stealth">
                                                Hello
                                            </LemonButton>
                                        </>
                                    ),
                                }}
                            />
                        </div>
                    </div>
                </div>
            )
        },
        [
            data.length,
            renderedRows.startIndex,
            renderedRows.stopIndex,
            currentBoxSizeAndPosition.top,
            currentBoxSizeAndPosition.height,
        ]
    )

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
                                    rowRenderer={rowRenderer}
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
