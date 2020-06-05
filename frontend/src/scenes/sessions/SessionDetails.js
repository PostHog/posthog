import React from 'react'
import { Table } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { EventDetails, formatEventName } from 'scenes/events'
import { Property } from 'lib/components/Property'

export function SessionDetails({ events }) {
    const columns = [
        {
            title: 'Event',
            key: 'id',
            render: function RenderEvent(event) {
                return formatEventName(event)
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
            title: 'Time',
            render: function RenderEvent({ timestamp }) {
                return <span>{humanFriendlyDetailedTime(timestamp)}</span>
            },
        },
    ]

    return (
        <Table
            columns={columns}
            rowKey={event => event.id}
            dataSource={events}
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
