import React from 'react'
import { Table } from 'antd'
import { humanFriendlyDiff, humanFriendlyDetailedTime } from '~/lib/utils'
import { EventDetails } from 'scenes/events'
import { Property } from 'lib/components/Property'
import { eventToName } from 'lib/utils'
import { EventType } from '~/types'

export function SessionDetails({ events }: { events: EventType[] }): JSX.Element {
    const columns = [
        {
            title: 'Event',
            key: 'id',
            render: function RenderEvent(event: EventType) {
                return eventToName(event)
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
                return <span>{index > 0 ? humanFriendlyDiff(events[index - 1]['timestamp'], timestamp) : 0}</span>
            },
        },
        {
            title: 'Order',
            render: function RenderOrder(_: Event, __: any, index: number) {
                return <span>{index + 1}</span>
            },
        },
    ]

    return (
        <Table
            columns={columns}
            rowKey={(event) => event.id}
            dataSource={events}
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
            expandable={{
                expandedRowRender: function renderExpand(event) {
                    return <EventDetails event={event} />
                },
                rowExpandable: (event) => !!event,
                expandRowByClick: true,
            }}
        />
    )
}
