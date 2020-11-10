import React, { useState } from 'react'
import { useValues } from 'kea'
import { Button, Table, Tooltip } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { PropertyUsageType } from '~/types'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function PropertiesVolumeTable(): JSX.Element {
    const columns = [
        {
            title: 'Property',
            render: function PropName(item: PropertyUsageType) {
                return <PropertyKeyInfo value={item.key} />
            },
            sorter: (a: PropertyUsageType, b: PropertyUsageType) => ('' + a.key).localeCompare(b.key),
            defaultSortOrder: 'ascend',
        },
        {
            title: function VolumeTitle() {
                return (
                    <Tooltip
                        placement="right"
                        title="Total number of events that included this property in the last 30 days. Can be delayed by up to an hour."
                    >
                        30 day volume
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            dataIndex: 'volume',

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
                        30 day queries
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            dataIndex: 'usage_count',
            sorter: (a: PropertyUsageType, b: PropertyUsageType) =>
                a.usage_count == b.usage_count ? a.volume - b.volume : a.usage_count - b.usage_count,
        },
    ]
    const { user } = useValues(userLogic)
    const [showPostHogProps, setShowPostHogProps] = useState(true)
    return (
        <div>
            <Button
                size="small"
                type={showPostHogProps ? 'primary' : 'default'}
                onClick={() => setShowPostHogProps(!showPostHogProps)}
            >
                {showPostHogProps ? 'Hide' : 'Show'} PostHog properties
            </Button>
            <br />
            <br />
            <Table
                dataSource={user?.team.event_properties_with_usage
                    .filter((item: PropertyUsageType) => (keyMapping.event[item.key] ? showPostHogProps : true))
                    .filter((item: PropertyUsageType) =>
                        keyMapping.event[item.key] && keyMapping.event[item.key].hide ? false : true
                    )}
                columns={columns}
                size="small"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            />
        </div>
    )
}
