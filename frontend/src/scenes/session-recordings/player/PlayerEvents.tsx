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
import { CellMeasurer } from 'react-virtualized/dist/commonjs/CellMeasurer'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogic, OVERSCANNED_ROW_COUNT } from 'scenes/session-recordings/player/eventsListLogic'
import { AutocaptureIcon, EventIcon, PageleaveIcon, PageviewIcon } from 'lib/components/icons'
import { capitalizeFirstLetter, eventToDescription, Loading } from 'lib/utils'
import { getKeyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { EventType } from '~/types'

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

const renderIcon = (event: EventType): JSX.Element => {
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

export function PlayerEvents(): JSX.Element {
    const listRef = useRef<List>(null)
    const { loading } = useValues(sessionRecordingLogic)
    const {
        localFilters,
        listEvents,
        cellMeasurerCache,
        currentEventsBoxSizeAndPosition,
        showPositionFinder,
        isRowIndexRendered,
        isEventCurrent,
        isDirectionUp,
        renderedRows,
    } = useValues(eventsListLogic)
    const { setLocalFilters, setRenderedRows, setList, scrollTo, disablePositionFinder } = useActions(eventsListLogic)

    useEffect(() => {
        if (listRef?.current) {
            setList(listRef.current)
        }
    }, [listRef.current])

    const rowRenderer = useCallback(
        function _rowRenderer({ index, style, key, parent }: ListRowProps): JSX.Element {
            const event = listEvents[index]
            const hasDescription = getKeyMapping(event.event, 'event')

            return (
                <CellMeasurer cache={cellMeasurerCache} parent={parent} columnIndex={0} key={key} rowIndex={index}>
                    <Row
                        className={clsx('event-list-item', { 'current-event': isEventCurrent(index) })}
                        align="top"
                        style={style}
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
                                <span className="event-item-content-subtitle">
                                    {capitalizeFirstLetter(eventToDescription(event))}
                                </span>
                            )}
                            <Skeleton active paragraph={{ rows: 2, width: ['40%', '100%'] }} title={false} />
                        </Col>
                    </Row>
                </CellMeasurer>
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
        [currentEventsBoxSizeAndPosition.top, currentEventsBoxSizeAndPosition.height, loading, listEvents.length]
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
                {loading ? (
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
                                        deferredMeasurementCache={cellMeasurerCache}
                                        overscanRowCount={OVERSCANNED_ROW_COUNT} // in case autoscrolling scrolls faster than we render.
                                        overscanIndicesGetter={overscanIndicesGetter}
                                        rowCount={listEvents.length}
                                        rowRenderer={rowRenderer}
                                        rowHeight={cellMeasurerCache.rowHeight}
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
