import './PlayerEvents.scss'
import React, { useEffect, useRef } from 'react'
import { Col, Input, Row, Skeleton } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, CloseOutlined, SearchOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
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

export function PlayerEvents(): JSX.Element {
    const listRef = useRef<VirtualizedList>(null)
    const { sessionEventsDataLoading } = useValues(sessionRecordingLogic)
    const {
        localFilters,
        listEvents,
        cellMeasurerCache,
        isEventCurrent,
        isRowIndexRendered,
        currentEventsBoxSizeAndPosition,
        showPositionFinder,
        isDirectionUp,
    } = useValues(eventsListLogic)
    const { setLocalFilters, setRenderedRows, setList, scrollTo } = useActions(eventsListLogic)

    function Event({ index, style, key, parent }: ListRowProps): JSX.Element {
        const event = listEvents[index]
        const hasDescription = getKeyMapping(event.event, 'event')
        const renderAllRows = listEvents.length <= OVERSCANNED_ROW_COUNT

        const renderIcon = (): JSX.Element => {
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

        return (
            <CellMeasurer cache={cellMeasurerCache} parent={parent} columnIndex={0} key={key} rowIndex={index}>
                <Row
                    className={clsx('event-list-item', { 'current-event': isEventCurrent(index) })}
                    align="top"
                    style={style}
                >
                    <Col className="event-item-icon">
                        <div className="event-item-icon-wrapper">{renderIcon()}</div>
                    </Col>
                    <Col
                        className={clsx('event-item-content', {
                            rendering: !renderAllRows && !isRowIndexRendered(index),
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
    }

    console.log('POSITION', showPositionFinder)

    function cellRangeRenderer(props: GridCellRangeProps): React.ReactNode[] {
        const children = defaultCellRangeRenderer(props)
        console.log('SCROLL LING', props.isScrolling, props.scrollTop)
        children.push(
            <div
                className="current-events-highlight-box"
                style={{
                    height: currentEventsBoxSizeAndPosition.height,
                    transform: `translateY(${currentEventsBoxSizeAndPosition.top}px)`,
                }}
            />
        )
        return children
    }

    useEffect(() => {
        if (listRef?.current) {
            setList(listRef.current)
        }
    }, [listRef.current])

    return (
        <Col className="player-events-container">
            <Input
                prefix={<SearchOutlined />}
                placeholder="Search for events"
                value={localFilters.query}
                onChange={(e) => setLocalFilters({ query: e.target.value })}
            />
            <Col className="event-list">
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
                        Jump to current event
                    </Row>
                    <Row className="right" align="middle" justify="center" wrap={false}>
                        <CloseOutlined />
                    </Row>
                </div>
                <AutoSizer>
                    {({ height, width }: { height: number; width: number }) => {
                        return (
                            <VirtualizedList
                                ref={listRef}
                                className="event-list-virtual"
                                height={height}
                                width={width}
                                onRowsRendered={setRenderedRows}
                                noRowsRenderer={sessionEventsDataLoading ? () => <Loading /> : undefined}
                                cellRangeRenderer={cellRangeRenderer}
                                deferredMeasurementCache={cellMeasurerCache}
                                overscanRowCount={OVERSCANNED_ROW_COUNT} // in case autoscrolling scrolls faster than we render.
                                overscanIndicesGetter={overscanIndicesGetter}
                                rowCount={listEvents.length}
                                rowRenderer={Event}
                                rowHeight={cellMeasurerCache.rowHeight}
                            />
                        )
                    }}
                </AutoSizer>
            </Col>
        </Col>
    )
}
