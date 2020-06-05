import React from 'react'
import { Table } from 'antd'
import { humanFriendlyDetailedTime } from '~/lib/utils'
import { EventDetails, formatEventName } from 'scenes/events'

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
