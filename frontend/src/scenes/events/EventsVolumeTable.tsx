import React, { useEffect, useState } from 'react'
import { useValues } from 'kea'
import { Alert, Input, Table, Tooltip } from 'antd'
import { userLogic } from 'scenes/userLogic'
import Fuse from 'fuse.js'
import { InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { humanizeNumber } from 'lib/utils'

const searchEvents = (sources: EventOrPropType[], search: string, key: 'event' | 'key'): EventOrPropType[] => {
    return new Fuse(sources, {
        keys: [key],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export interface EventOrPropType {
    event?: string
    key?: string
    usage_count: number
    volume: number
    warnings: string[]
}

export function VolumeTable({ type, data }: { type: 'event' | 'key'; data: EventOrPropType[] }): JSX.Element {
    const [searchTerm, setSearchTerm] = useState(false as string | false)
    const [dataWithWarnings, setDataWithWarnings] = useState([] as EventOrPropType[])
    const num_warnings = dataWithWarnings.reduce((prev, item) => {
        return prev + (item.warnings?.length || 0)
    }, 0)
    const columns = [
        {
            title: type,
            render: function RenderEvent(item: EventOrPropType): JSX.Element {
                return <span className="ph-no-capture">{item[type]}</span>
            },
            sorter: (a: EventOrPropType, b: EventOrPropType) => ('' + a[type]).localeCompare(b[type] || ''),
        },
        {
            title: `Warnings (${num_warnings})`,
            render: function RenderEvent(item: EventOrPropType): JSX.Element {
                return (
                    <>
                        {!item.warnings?.length && '-'}
                        {item.warnings?.map((warning) => (
                            <Tooltip key={warning} color="orange" title={<>Warning! {warning}</>}>
                                <WarningOutlined style={{ color: 'var(--warning)' }} />
                            </Tooltip>
                        ))}
                    </>
                )
            },
            sorter: (a: EventOrPropType, b: EventOrPropType) => b.warnings.length - a.warnings.length,
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
            render: function RenderVolume(item: EventOrPropType) {
                return <span className="ph-no-capture">{humanizeNumber(item.volume)}</span>
            },
            sorter: (a: EventOrPropType, b: EventOrPropType) =>
                a.volume == b.volume ? a.usage_count - b.usage_count : a.volume - b.volume,
        },
        {
            title: function QueriesTitle() {
                return (
                    <Tooltip
                        placement="right"
                        title={<>Number of queries in PostHog that included a filter on this {type}.</>}
                    >
                        30 day queries (delayed by up to an hour)
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                )
            },
            // eslint-disable-next-line react/display-name
            render: (item: EventOrPropType) => (
                <span className="ph-no-capture">{humanizeNumber(item.usage_count)}</span>
            ),
            sorter: (a: EventOrPropType, b: EventOrPropType) =>
                a.usage_count == b.usage_count ? a.volume - b.volume : a.usage_count - b.usage_count,
        },
    ]
    useEffect(() => {
        setDataWithWarnings(
            data.map(
                (item): EventOrPropType => {
                    item.warnings = []
                    if (item[type]?.endsWith(' ')) {
                        item.warnings.push(`This ${type} ends with a space.`)
                    }
                    if (item[type]?.startsWith(' ')) {
                        item.warnings.push(`This ${type} starts with a space.`)
                    }
                    return item
                }
            ) || []
        )
    }, [])
    return (
        <>
            <Input.Search
                allowClear
                enterButton
                style={{ marginTop: '1.5rem', maxWidth: 400, width: 'initial', flexGrow: 1 }}
                onChange={(e) => {
                    setSearchTerm(e.target.value)
                }}
            />
            <br />
            <br />
            <Table
                dataSource={searchTerm ? searchEvents(dataWithWarnings, searchTerm, type) : dataWithWarnings}
                columns={columns}
                rowKey={type}
                size="small"
                style={{ marginBottom: '4rem' }}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            />
        </>
    )
}

export function UsageDisabledWarning({ tab }: { tab: string }): JSX.Element {
    return (
        <Alert
            type="warning"
            message={
                <>
                    {tab} is not enabled on your instance. If you want to enable event usage please set the follow
                    environment variable: <pre style={{ display: 'inline' }}>ASYNC_EVENT_PROPERTY_USAGE=1</pre>
                    <br />
                    <br />
                    Please note, enabling this environment variable can increase load considerably if you have a large
                    volume of events.
                </>
            }
        />
    )
}

export function EventsVolumeTable(): JSX.Element | null {
    const { user } = useValues(userLogic)

    return user?.team?.event_names_with_usage ? (
        <>
            {!user?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning tab="Properties Stats" />
            ) : (
                user?.team?.event_names_with_usage[0]?.volume === null && (
                    <>
                        <Alert
                            type="warning"
                            message="We haven't been able to get usage and volume data yet. Please check back later"
                        />
                    </>
                )
            )}
            <VolumeTable data={user?.team?.event_names_with_usage as EventOrPropType[]} type="event" />
        </>
    ) : null
}
