import React, { useState } from 'react'
import { Table } from 'antd'
import { humanFriendlyDiff, humanFriendlyDetailedTime } from '~/lib/utils'
import { EventDetails } from 'scenes/events'
import { Property } from 'lib/components/Property'
import { eventToName } from 'lib/utils'
import { EventType } from '~/types'

export function SessionDetails({ events }: { events: EventType[] | undefined }): JSX.Element {
    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(50)

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
            dataSource={events}
            loading={events === undefined}
            pagination={{
                pageSize: pageSize,
                hideOnSinglePage: !events || events.length < 10,
                showSizeChanger: true,
                pageSizeOptions: ['10', '20', '50', '100', '200', '500'],
                onChange: (page, pageSize) => {
                    setPage(page)
                    setPageSize(pageSize || 50)
                },
            }}
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
