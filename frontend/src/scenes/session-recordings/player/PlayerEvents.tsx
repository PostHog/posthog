import './PlayerEvents.scss'
import React from 'react'
import { Col, Input, Row } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized/dist/commonjs/AutoSizer'
import { CellMeasurer } from 'react-virtualized/dist/commonjs/CellMeasurer'
import { eventsListLogic } from 'scenes/session-recordings/player/eventsListLogic'
import { AutocaptureIcon, EventIcon, PageleaveIcon, PageviewIcon } from 'lib/components/icons'
import { capitalizeFirstLetter, eventToDescription } from 'lib/utils'
import { getKeyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function PlayerEvents(): JSX.Element {
    const { localFilters, listEvents, cellMeasurerCache } = useValues(eventsListLogic)
    const { setLocalFilters } = useActions(eventsListLogic)

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
                <Row className="event-list-item" align="top" style={style}>
                    <Col className="event-item-icon">
                        <div className="event-item-icon-wrapper">{renderIcon()}</div>
                    </Col>
                    <Col className="event-item-text">
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
                    </Col>
                </Row>
            </CellMeasurer>
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
                                height={height}
                                width={width}
                                deferredMeasurementCache={cellMeasurerCache}
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
