import React, { useEffect, useMemo, useState } from 'react'
import { Table } from 'antd'
import { humanFriendlyDetailedTime, colonDelimitedDiff } from '~/lib/utils'
import { EventDetails } from 'scenes/events'
import { Property } from 'lib/components/Property'
import { eventToName } from 'lib/utils'
import { EventType, SessionType } from '~/types'
import { useActions, useValues } from 'kea'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { ANTD_EXPAND_BUTTON_WIDTH } from 'lib/components/ResizableTable'
import { MATCHING_EVENT_ICON_SIZE } from 'scenes/sessions/SessionsView'
import { ExpandIcon } from 'lib/components/ExpandIcon'
import { InfoCircleOutlined, MonitorOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'

export function SessionDetails({ session }: { session: SessionType }): JSX.Element {
    const { filteredSessionEvents } = useValues(sessionsTableLogic)
    const { loadSessionEvents } = useActions(sessionsTableLogic)

    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(50)
    const events = filteredSessionEvents[session.global_session_id]
    const matchingEventIds = useMemo(() => new Set(session.matching_events || []), [session.matching_events])

    useEffect(() => {
        if (!events) {
            loadSessionEvents(session)
        }
    }, [])

    const columns = [
        {
            title: 'Event',
            key: 'id',
            render: function RenderEvent(event: EventType) {
                return <PropertyKeyInfo value={eventToName(event)} ellipsis={false} />
            },
        },
        {
            title: 'URL / Screen',
            key: 'url',
            render: function renderURL(event: EventType) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                const param = event.properties['$current_url'] ? '$current_url' : '$screen_name'
                return <Property value={event.properties[param]} />
            },
            ellipsis: true,
        },
        {
            title: 'Timestamp',
            render: function RenderTimestamp({ timestamp }: EventType) {
                return <span>{humanFriendlyDetailedTime(timestamp, true)}</span>
            },
        },
        {
            title: (
                <span>
                    Time Elapsed from Previous
                    <Tooltip title="Time elapsed is formatted as HH:MM:SS.">
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                </span>
            ),
            render: function RenderElapsed({ timestamp }: EventType, _: any, index: number) {
                const realIndex = (page - 1) * pageSize + index
                const lastEvent = realIndex > 0 ? events?.[realIndex - 1] : null
                return <span>{lastEvent ? colonDelimitedDiff(lastEvent.timestamp, timestamp) : '00:00:00'}</span>
            },
        },
    ]
    return (
        <Table
            columns={columns}
            rowKey="id"
            rowClassName={(event: EventType) => (matchingEventIds.has(event.id) ? 'sessions-event-highlighted' : '')}
            dataSource={events}
            loading={!events}
            pagination={{
                pageSize: pageSize,
                hideOnSinglePage: !events || events.length < 10,
                showSizeChanger: true,
                pageSizeOptions: ['10', '20', '50', '100', '200', '500'],
                onChange: (changedPage, changedPageSize) => {
                    setPage(changedPage)
                    setPageSize(changedPageSize || 50)
                },
            }}
            expandable={{
                expandedRowRender: function renderExpand(event) {
                    return <EventDetails event={event} />
                },
                rowExpandable: (event) => !!event,
                expandRowByClick: true,
                columnWidth: ANTD_EXPAND_BUTTON_WIDTH + MATCHING_EVENT_ICON_SIZE,
                expandIcon: function _renderExpandIcon(expandProps) {
                    const { record: event } = expandProps
                    return (
                        <ExpandIcon {...expandProps}>
                            {matchingEventIds.has(event.id) ? (
                                <Tooltip title="Matches your event filters">
                                    <div className="sessions-event-matching-events-icon cursor-pointer ml-05">
                                        <MonitorOutlined />
                                    </div>
                                </Tooltip>
                            ) : (
                                <></>
                            )}
                        </ExpandIcon>
                    )
                },
            }}
        />
    )
}
