import React from 'react'
import { Col, Input, Row } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized/dist/commonjs/AutoSizer'
import { CellMeasurer } from 'react-virtualized/dist/commonjs/CellMeasurer'
import { eventsListLogic } from 'scenes/session-recordings/player/eventsListLogic'
import { ActionIcon, AutocaptureIcon, EventIcon, PageleaveIcon, PageviewIcon } from 'lib/components/icons'
import { eventToName } from 'lib/utils'

export function PlayerEvents(): JSX.Element {
    const { localFilters, listEvents, cellMeasurerCache } = useValues(eventsListLogic)
    const { setLocalFilters } = useActions(eventsListLogic)

    function Event({ index, style, key, parent }: ListRowProps): JSX.Element {
        const event = listEvents[index]

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
            if (event.event.startsWith('$')) {
                return <EventIcon />
            }
            return <ActionIcon />
        }

        return (
            <CellMeasurer cache={cellMeasurerCache} parent={parent} columnIndex={0} key={key} rowIndex={index}>
                <Row className="event-list-item" align="top" style={style}>
                    <Col className="event-item-icon">{renderIcon()}</Col>
                    <Col className="event-item-text">{eventToName(event, true)}</Col>
                    <Col>{event.colonTimestamp}</Col>
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
