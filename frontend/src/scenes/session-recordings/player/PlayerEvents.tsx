import React from 'react'
import { Col, Input, Row } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogic } from 'scenes/session-recordings/player/eventsListLogic'
import { EventType } from '~/types'
import { ActionIcon, AutocaptureIcon, EventIcon, PageleaveIcon, PageviewIcon } from 'lib/components/icons'

function Event({ event }: { event: EventType }): JSX.Element {
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
        <Row className="event-list-item">
            {renderIcon()}
            <Col>{event.event}</Col>
            {event.timestamp}
        </Row>
    )
}

export function PlayerEvents(): JSX.Element {
    const { localFilters } = useValues(eventsListLogic)
    const { setLocalFilters } = useActions(eventsListLogic)
    const { filteredSessionEvents } = useValues(sessionRecordingLogic)

    return (
        <Col className="player-events-container">
            <Input
                prefix={<SearchOutlined />}
                placeholder="Search for events"
                value={localFilters.query}
                onChange={(e) => setLocalFilters({ query: e.target.value })}
            />
            <Col className="event-list">
                {filteredSessionEvents.map((event: EventType) => (
                    <Event key={event.id} event={event} />
                ))}
            </Col>
        </Col>
    )
}
