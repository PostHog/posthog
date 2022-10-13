import './PlayerEvents.scss'
import React, { useCallback, useEffect, useRef } from 'react'
import { Col, Empty, Input, Row, Skeleton } from 'antd'
import {
    ArrowDownOutlined,
    ArrowUpOutlined,
    CloseOutlined,
    SearchOutlined,
    InfoCircleOutlined,
} from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import List, { ListRowProps } from 'react-virtualized/dist/es/List'
import {
    defaultCellRangeRenderer,
    GridCellRangeProps,
    OverscanIndices,
    OverscanIndicesGetterParams,
} from 'react-virtualized/dist/es/Grid'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import {
    eventsListLogic,
    OVERSCANNED_ROW_COUNT,
    DEFAULT_ROW_HEIGHT,
} from 'scenes/session-recordings/player/list/eventsListLogic'
import { IconAutocapture, IconEvent, IconPageleave, IconPageview } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { capitalizeFirstLetter, eventToDescription, isEllipsisActive } from 'lib/utils'
import { getKeyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { RecordingEventType, SessionRecordingPlayerProps } from '~/types'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'

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
        return <IconPageview />
    }
    if (event.event === '$pageleave') {
        return <IconPageleave />
    }
    if (event.event === '$autocapture') {
        return <IconAutocapture />
    }
    return <IconEvent />
    // TODO: Have api/events return `event_type` parameter to help distinguish btwn custom events, events, and actions
    // return <IconAction />
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

export function PlayerEvents({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const listRef = useRef<List>(null)
    const {
        eventListData,
        localFilters,
        currentBoxSizeAndPosition,
        showPositionFinder,
        isRowIndexRendered,
        isCurrent,
        isDirectionUp,
        renderedRows,
    } = useValues(eventsListLogic({ sessionRecordingId, playerKey }))
    const { sessionEventsDataLoading } = useValues(sessionRecordingDataLogic({ sessionRecordingId }))
    const { setLocalFilters, setRenderedRows, setList, scrollTo, disablePositionFinder, handleEventClick } = useActions(
        eventsListLogic({ sessionRecordingId, playerKey })
    )

    useEffect(() => {
        if (listRef?.current) {
            setList(listRef.current)
        }
    }, [listRef.current])

    const rowRenderer = useCallback(
        function _rowRenderer({ index, style, key }: ListRowProps): JSX.Element {
            const event = eventListData[index]
            const hasDescription = getKeyMapping(event.event, 'event')
            const isEventCurrent = isCurrent(index)

            return (
                <Row
                    key={key}
                    className={clsx('event-list-item', { 'current-event': isEventCurrent })}
                    align="top"
                    style={{ ...style, zIndex: eventListData.length - index }}
                    onClick={() => {
                        event.playerPosition && handleEventClick(event.playerPosition)
                    }}
                    data-attr="recording-event-list"
                >
                    <Col className="event-item-icon">
                        <div className="event-item-icon-wrapper">{renderIcon(event)}</div>
                    </Col>
                    <Col
                        className={clsx('event-item-content', {
                            rendering: !isRowIndexRendered(index),
                            'out-of-band-event': event.isOutOfBand,
                        })}
                    >
                        <Row className="event-item-content-top-row">
                            <div>
                                <PropertyKeyInfo
                                    className="event-item-content-title"
                                    value={event.event}
                                    disableIcon
                                    disablePopover
                                    ellipsis={true}
                                />
                                {event.isOutOfBand && (
                                    <Tooltip
                                        className="out-of-band-event-tooltip"
                                        title={
                                            <>
                                                <b>Out of band event</b>
                                                <p>
                                                    This event originated from a different client library than this
                                                    recording. As a result, it's timing and placement might not be
                                                    precise.
                                                </p>
                                            </>
                                        }
                                    >
                                        <InfoCircleOutlined />
                                    </Tooltip>
                                )}
                            </div>
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
            eventListData.length,
            renderedRows.startIndex,
            renderedRows.stopIndex,
            currentBoxSizeAndPosition.top,
            currentBoxSizeAndPosition.height,
        ]
    )

    const cellRangeRenderer = useCallback(
        function _cellRangeRenderer(props: GridCellRangeProps): React.ReactNode[] {
            const children = defaultCellRangeRenderer(props)
            if (eventListData.length > 0) {
                children.push(
                    <div
                        key="highlight-box"
                        className="current-events-highlight-box"
                        style={{
                            height: currentBoxSizeAndPosition.height,
                            transform: `translateY(${currentBoxSizeAndPosition.top}px)`,
                        }}
                    />
                )
            }
            return children
        },
        [
            currentBoxSizeAndPosition.top,
            currentBoxSizeAndPosition.height,
            sessionEventsDataLoading,
            eventListData.length,
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
                {sessionEventsDataLoading ? (
                    <SpinnerOverlay />
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
                                        rowCount={eventListData.length}
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
