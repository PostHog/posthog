import React from 'react'
import { Table } from 'antd'
import { humanFriendlyDiff, humanFriendlyDetailedTime } from '~/lib/utils'
import { EventDetails } from 'scenes/events'
import { Property } from 'lib/components/Property'
import { eventToName } from 'lib/utils'

export function SessionDetails({ events }) {
    const columns = [
        {
            title: 'Event',
            key: 'id',
            render: function RenderEvent(event) {
                return eventToName(event)
            },
        },
        {
            title: 'URL / Screen',
            key: 'url',
            render: function renderURL(event) {
                if (!event) return { props: { colSpan: 0 } }
                let param = event.properties['$current_url'] ? '$current_url' : '$screen_name'
                return <Property value={event.properties[param]} />
            },
            ellipsis: true,
        },
        {
            title: 'Timestamp',
            render: function RenderTimestamp({ timestamp }) {
                return <span>{humanFriendlyDetailedTime(timestamp, true)}</span>
            },
        },
        {
            title: 'Time Elapsed from Previous',
            render: function RenderElapsed({ timestamp }, _, index) {
                return <span>{index > 0 ? humanFriendlyDiff(events[index - 1]['timestamp'], timestamp) : 0}</span>
            },
        },
        {
            title: 'Order',
            render: function RenderOrder(_, __, index) {
                return <span>{index + 1}</span>
            },
        },
    ]

    return (
        <Table
            columns={columns}
            rowKey={event => event.id}
            dataSource={events}
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
            expandable={{
                expandedRowRender: function renderExpand(event) {
                    return <EventDetails event={event} />
                },
                rowExpandable: event => event,
                expandRowByClick: true,
            }}
        ></Table>
    )
}
