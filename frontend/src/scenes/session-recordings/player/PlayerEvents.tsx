import './PlayerEvents.scss'
import React, { useCallback, useEffect, useRef } from 'react'
import { Col, Empty, Input, Row, Skeleton } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, CloseOutlined, SearchOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import List, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import {
    defaultCellRangeRenderer,
    GridCellRangeProps,
    OverscanIndices,
    OverscanIndicesGetterParams,
} from 'react-virtualized/dist/commonjs/Grid'
import { AutoSizer } from 'react-virtualized/dist/commonjs/AutoSizer'
import {
    eventsListLogic,
    OVERSCANNED_ROW_COUNT,
    DEFAULT_ROW_HEIGHT,
} from 'scenes/session-recordings/player/eventsListLogic'
import { AutocaptureIcon, EventIcon, PageleaveIcon, PageviewIcon } from 'lib/components/icons'
import { capitalizeFirstLetter, eventToDescription, isEllipsisActive, Loading } from 'lib/utils'
import { getKeyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { RecordingEventType } from '~/types'

function overscanIndicesGetter({
    cellCount,
    overscanCellsCount,
    startIndex,
    stopIndex,
}: OverscanIndicesGetterParams): OverscanIndices {
    const under = Math.floor(overscanCellsCount / 2)
    const over = overscanCellsCount - under
    return {
        overscanStartIndex: Math.max(0, startIndex - under),
        overscanStopIndex: Math.min(cellCount - 1, stopIndex + over),
    }
}

const renderIcon = (event: RecordingEventType): JSX.Element => {
    if (event.event === '$pageview') {
        return <PageviewIcon />
    }
    if (event.event === '$pageleave') {
        return <PageleaveIcon />
    }
    if (event.event === '$autocapture') {
        return <AutocaptureIcon />
    }
    return <EventIcon />
    // TODO: Have api/events return `event_type` parameter to help distinguish btwn custom events, events, and actions
    // return <ActionIcon />
}

function noRowsRenderer(): JSX.Element {
    return (
        <div className="event-list-empty-container">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No events fired in this recording." />
        </div>
    )
}

function EventDescription({ description }: { description: string }): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    return (
        <span
            className={clsx('event-item-content-subtitle', isEllipsisActive(ref.current) && 'overflowing')}
            title={description}
        >
            <div className="inner" ref={ref}>
                {description}
            </div>
        </span>
    )
}

export function PlayerEvents(): JSX.Element {
    const listRef = useRef<List>(null)
    const {
        localFilters,
        listEvents,
        currentEventsBoxSizeAndPosition,
        showPositionFinder,
        isRowIndexRendered,
        isEventCurrent,
        isDirectionUp,
        renderedRows,
        isEventListLoading,
    } = useValues(eventsListLogic)
    const { setLocalFilters, setRenderedRows, setList, scrollTo, disablePositionFinder, handleEventClick } =
        useActions(eventsListLogic)

    useEffect(() => {
        if (listRef?.current) {
            setList(listRef.current)
        }
    }, [listRef.current])

    const rowRenderer = useCallback(
        function _rowRenderer({ index, style, key }: ListRowProps): JSX.Element {
            const event = listEvents[index]
            const hasDescription = getKeyMapping(event.event, 'event')
            const isCurrent = isEventCurrent(index)

            return (
                <Row
                    key={key}
                    className={clsx('event-list-item', { 'current-event': isCurrent })}
                    align="top"
                    style={{ ...style, zIndex: listEvents.length - index }}
                    onClick={() => {
                        handleEventClick(event.timestamp)
                    }}
                >
                    <Col className="event-item-icon">
                        <div className="event-item-icon-wrapper">{renderIcon(event)}</div>
                    </Col>
                    <Col
                        className={clsx('event-item-content', {
                            rendering: !isRowIndexRendered(index),
                        })}
                    >
                        <Row className="event-item-content-top-row">
                            <PropertyKeyInfo
                                className="event-item-content-title"
                                value={event.event}
                                disableIcon
                                disablePopover
                                ellipsis={true}
                            />
                            <span className="event-item-content-timestamp">{event.colonTimestamp}</span>
                        </Row>
                        {hasDescription && (
                            <EventDescription description={capitalizeFirstLetter(eventToDescription(event, true))} />
                        )}
                        <Skeleton active paragraph={{ rows: 2, width: ['40%', '100%'] }} title={false} />
                    </Col>
                </Row>
            )
        },
        [
            listEvents.length,
            renderedRows.startIndex,
            renderedRows.stopIndex,
            currentEventsBoxSizeAndPosition.top,
            currentEventsBoxSizeAndPosition.height,
        ]
    )

    const cellRangeRenderer = useCallback(
        function _cellRangeRenderer(props: GridCellRangeProps): React.ReactNode[] {
            const children = defaultCellRangeRenderer(props)
            if (listEvents.length > 0) {
                children.push(
                    <div
                        key="highlight-box"
                        className="current-events-highlight-box"
                        style={{
                            height: currentEventsBoxSizeAndPosition.height,
                            transform: `translateY(${currentEventsBoxSizeAndPosition.top}px)`,
                        }}
                    />
                )
            }
            return children
        },
        [
            currentEventsBoxSizeAndPosition.top,
            currentEventsBoxSizeAndPosition.height,
            isEventListLoading,
            listEvents.length,
        ]
    )

    return (
        <Col className="player-events-container">
            <Input
                prefix={<SearchOutlined />}
                placeholder="Search for events"
                value={localFilters.query}
                onChange={(e) => setLocalFilters({ query: e.target.value })}
            />
            <Col className="event-list">
                {isEventListLoading ? (
                    <Loading />
                ) : (
                    <>
                        <div className={clsx('current-events-position-finder', { visible: showPositionFinder })}>
                            <Row
                                className="left"
                                align="middle"
                                wrap={false}
                                onClick={() => {
                                    scrollTo()
                                }}
                            >
                                {isDirectionUp ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                                Jump to current time
                            </Row>
                            <Row
                                className="right"
                                align="middle"
                                justify="center"
                                wrap={false}
                                onClick={() => {
                                    disablePositionFinder()
                                }}
                            >
                                <CloseOutlined />
                            </Row>
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
                                        noRowsRenderer={noRowsRenderer}
                                        cellRangeRenderer={cellRangeRenderer}
                                        overscanRowCount={OVERSCANNED_ROW_COUNT} // in case autoscrolling scrolls faster than we render.
                                        overscanIndicesGetter={overscanIndicesGetter}
                                        rowCount={listEvents.length}
                                        rowRenderer={rowRenderer}
                                        rowHeight={DEFAULT_ROW_HEIGHT}
                                    />
                                )
                            }}
                        </AutoSizer>
                    </>
                )}
            </Col>
        </Col>
    )
}
