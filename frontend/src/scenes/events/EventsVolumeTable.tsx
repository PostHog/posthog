import React from 'react'
import { useValues } from 'kea'
import { Table, Tooltip } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { EventUsageType } from '~/types'
import { humanizeNumber } from 'lib/utils'

export function EventsVolumeTable(): JSX.Element {
    const columns = [
        {
            title: 'Event',
            dataIndex: 'event',

            sorter: (a: EventUsageType, b: EventUsageType) => ('' + a.event).localeCompare(b.event),
        },
        {
            title: function VolumeTitle() {
                return (
                    <Tooltip
                        placement="right"
                        title="Total number of events over the last 30 days. Can be delayed by up to an hour."
                    >
                        30 day volume
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            render: (item: EventUsageType) => humanizeNumber(item.volume),
            sorter: (a: EventUsageType, b: EventUsageType) =>
                a.volume == b.volume ? a.usage_count - b.usage_count : a.volume - b.volume,
        },
        {
            title: function QueriesTitle() {
                return (
                    <Tooltip
                        placement="right"
                        title="Number of queries in PostHog that included a filter on this event."
                    >
                        30 day queries
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            render: (item: EventUsageType) => humanizeNumber(item.usage_count),
            sorter: (a: EventUsageType, b: EventUsageType) =>
                a.usage_count == b.usage_count ? a.volume - b.volume : a.usage_count - b.usage_count,
        },
    ]
    const { user } = useValues(userLogic)
    return (
        <Table
            dataSource={user?.team.event_names_with_usage}
            columns={columns}
            size="small"
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
        />
    )
}
