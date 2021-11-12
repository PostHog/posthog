import './PlayerEvents.scss'
import React, { useRef } from 'react'
import { Col, Input, Row, Skeleton } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized/dist/commonjs/AutoSizer'
import { CellMeasurer } from 'react-virtualized/dist/commonjs/CellMeasurer'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogic, OVERSCANNED_ROW_COUNT } from 'scenes/session-recordings/player/eventsListLogic'
import { AutocaptureIcon, EventIcon, PageleaveIcon, PageviewIcon } from 'lib/components/icons'
import { capitalizeFirstLetter, eventToDescription, Loading } from 'lib/utils'
import { getKeyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function PlayerEvents(): JSX.Element {
    const { sessionEventsDataLoading } = useValues(sessionRecordingLogic)
    const { localFilters, listEvents, cellMeasurerCache, isEventCurrent, isRowIndexRendered } =
        useValues(eventsListLogic)
    const { setLocalFilters, setRenderedRows } = useActions(eventsListLogic)

    function Event({ index, style, key, parent }: ListRowProps): JSX.Element {
        const event = listEvents[index]
        const hasDescription = getKeyMapping(event.event, 'event')

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
                    <Col className={clsx('event-item-text', { rendering: !isRowIndexRendered(index) })}>
                        <Row className="event-item-text-top-row">
                            <PropertyKeyInfo
                                className="event-item-text-title"
                                value={event.event}
                                disableIcon
                                disablePopover
                                ellipsis={false}
                            />
                            {event.colonTimestamp}
                        </Row>
                        {hasDescription && (
                            <span className="event-item-text-subtitle">
                                {capitalizeFirstLetter(eventToDescription(event))}
                            </span>
                        )}
                        <Skeleton active paragraph={{ rows: 2, width: ['40%', '100%'] }} title={false} />
                    </Col>
                    <Col>{event.colonTimestamp}</Col>
                </Row>
            </CellMeasurer>
        )
    }

    const listRef = useRef(null)

    if (listRef?.current?.Grid.state.instanceProps.rowSizeAndPositionManager.getCellCount() > 0) {
        console.log(
            'list ref',
            listRef.current,
            listRef?.current?.Grid.state.instanceProps.rowSizeAndPositionManager.getSizeAndPositionOfCell(32)
        )
    }

    return (
        <Col className="player-events-container">
            <Input
                prefix={<SearchOutlined />}
                placeholder="Search for events"
                value={localFilters.query}
                onChange={(e) => setLocalFilters({ query: e.target.value })}
            />
            <Col className="event-list">
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
                                // scrollToIndex={currentEventStartIndex}
                                // scrollToAlignment="center"
                                deferredMeasurementCache={cellMeasurerCache}
                                overscanRowCount={OVERSCANNED_ROW_COUNT} // in case autoscrolling scrolls faster than we render.
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
