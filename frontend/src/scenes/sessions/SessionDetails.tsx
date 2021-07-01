import React, { useEffect, useState } from 'react'
import { Table, Tooltip } from 'antd'
import { humanFriendlyDiff, humanFriendlyDetailedTime } from '~/lib/utils'
import { EventDetails } from 'scenes/events'
import { Property } from 'lib/components/Property'
import { eventToName } from 'lib/utils'
import { EventType, SessionType } from '~/types'
import { useActions, useValues } from 'kea'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import ExpandIcon from 'lib/components/ExpandIcon'
import { IconEventsShort } from 'lib/components/icons'
import { MATCHING_EVENT_ICON_SIZE } from 'scenes/sessions/SessionsView'
import { ANTD_EXPAND_BUTTON_WIDTH } from 'lib/components/ResizableTable'

export function SessionDetails({ session }: { session: SessionType }): JSX.Element {
    const { filteredSessionEvents } = useValues(sessionsTableLogic)
    const { loadSessionEvents } = useActions(sessionsTableLogic)

    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(50)
    const events = session.events || filteredSessionEvents[session.global_session_id]

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
            title: 'Time Elapsed from Previous',
            render: function RenderElapsed({ timestamp }: EventType, _: any, index: number) {
                const realIndex = (page - 1) * pageSize + index
                const lastEvent = realIndex > 0 ? events?.[realIndex - 1] : null
                return <span>{lastEvent ? humanFriendlyDiff(lastEvent.timestamp, timestamp) : 0}</span>
            },
        },
        {
            title: 'Order',
            render: function RenderOrder(_: Event, __: any, index: number) {
                const realIndex = (page - 1) * pageSize + index
                return <span>{realIndex + 1}</span>
            },
        },
    ]
    return (
        <Table
            columns={columns}
            rowKey="id"
            rowClassName={(event: EventType) =>
                (session.matching_events || []).includes(event.id) ? 'sessions-event-highlighted' : ''
            }
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
                            {(session.matching_events || []).includes(event.id) ? (
                                <Tooltip title="This event matches your event filters">
                                    <div className="sessions-matching-events-icon cursor-pointer">
                                        <IconEventsShort size={MATCHING_EVENT_ICON_SIZE} />
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
