import React from 'react'
import { useValues } from 'kea'
import { Alert, Table, Tooltip } from 'antd'
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
                        30 day volume (delayed by up to an hour)
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            // eslint-disable-next-line react/display-name
            render: (
                item: EventUsageType // https://stackoverflow.com/questions/55620562/eslint-component-definition-is-missing-displayname-react-display-name
            ) => <span className="ph-no-capture">{humanizeNumber(item.volume)}</span>,
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
                        30 day queries (delayed by up to an hour)
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            // eslint-disable-next-line react/display-name
            render: (item: EventUsageType) => <span className="ph-no-capture">{humanizeNumber(item.usage_count)}</span>,
            sorter: (a: EventUsageType, b: EventUsageType) =>
                a.usage_count == b.usage_count ? a.volume - b.volume : a.usage_count - b.usage_count,
        },
    ]
    const { user } = useValues(userLogic)
    return (
        <>
            {user?.team?.event_names_with_usage[0]?.volume === null && (
                <>
                    <Alert
                        type="warning"
                        message="We haven't been able to get usage and volume data yet. Please check back later"
                    />
                    <br />
                </>
            )}
            <Table
                dataSource={user?.team?.event_names_with_usage}
                columns={columns}
                rowKey="event"
                size="small"
                style={{ marginBottom: '4rem' }}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            />
        </>
    )
}
