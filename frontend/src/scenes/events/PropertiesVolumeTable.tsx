import React, { useState } from 'react'
import { useValues } from 'kea'
import { Alert, Button, Table, Tooltip } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { PropertyUsageType } from '~/types'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { humanizeNumber } from 'lib/utils'

const columns = [
    {
        title: 'Property',
        render: function PropName(item: PropertyUsageType) {
            return <PropertyKeyInfo value={item.key} />
        },
        sorter: (a: PropertyUsageType, b: PropertyUsageType) => {
            // If PostHog property, put at end of list
            if (keyMapping.event[a.key] && !keyMapping.event[b.key]) {
                return 1
            }
            if (!keyMapping.event[a.key] && keyMapping.event[b.key]) {
                return -1
            }
            return ('' + a.key).localeCompare(b.key)
        },
        defaultSortOrder: 'ascend',
    },
    {
        title: function VolumeTitle() {
            return (
                <Tooltip
                    placement="right"
                    title="Total number of events that included this property in the last 30 days. Can be delayed by up to an hour."
                >
                    30 day volume (delayed by up to an hour)
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            )
        },
        render: (item: PropertyUsageType) => humanizeNumber(item.volume),
        sorter: (a: PropertyUsageType, b: PropertyUsageType) =>
            a.volume == b.volume ? a.usage_count - b.usage_count : a.volume - b.volume,
    },
    {
        title: function QueriesTitle() {
            return (
                <Tooltip
                    placement="right"
                    title="Number of queries in PostHog that included a filter on this property."
                >
                    30 day queries (delayed by up to an hour)
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            )
        },
        render: (item: PropertyUsageType) => humanizeNumber(item.usage_count),
        sorter: (a: PropertyUsageType, b: PropertyUsageType) =>
            a.usage_count == b.usage_count ? a.volume - b.volume : a.usage_count - b.usage_count,
    },
]

export function PropertiesVolumeTable(): JSX.Element {
    const { user } = useValues(userLogic)
    const [showPostHogProps, setShowPostHogProps] = useState(true)
    return (
        <div>
            <Button size="small" type="default" onClick={() => setShowPostHogProps(!showPostHogProps)}>
                {showPostHogProps ? 'Hide' : 'Show'} PostHog properties
            </Button>
            <br />
            <br />
            {user?.team.event_properties_with_usage[0]?.volume === null && (
                <>
                    <Alert
                        type="warning"
                        description="We haven't been able to get usage and volume data yet. Please check back later"
                    />
                    <br />
                </>
            )}
            <Table
                dataSource={user?.team.event_properties_with_usage
                    .filter((item: PropertyUsageType) => (keyMapping.event[item.key] ? showPostHogProps : true))
                    .filter((item: PropertyUsageType) =>
                        keyMapping.event[item.key] && keyMapping.event[item.key].hide ? false : true
                    )}
                rowKey="event"
                columns={columns}
                style={{ marginBottom: '4rem' }}
                size="small"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            />
        </div>
    )
}
