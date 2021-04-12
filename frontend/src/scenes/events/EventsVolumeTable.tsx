import React, { useEffect, useState } from 'react'
import { useValues } from 'kea'
import { Alert, Input, Table, Tooltip } from 'antd'
import Fuse from 'fuse.js'
import { InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { humanizeNumber } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { ColumnsType } from 'antd/lib/table'

export interface EventOrPropType {
    event?: string
    key?: string
    usage_count: number
    volume: number
    warnings: string[]
}

type EventTableType = 'event' | 'property'

const searchEvents = (sources: EventOrPropType[], search: string, key: EventTableType): EventOrPropType[] => {
    return new Fuse(sources, {
        keys: [key],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export function VolumeTable({ type, data }: { type: EventTableType; data: EventOrPropType[] }): JSX.Element {
    const [searchTerm, setSearchTerm] = useState(false as string | false)
    const [dataWithWarnings, setDataWithWarnings] = useState([] as EventOrPropType[])

    const key = type === 'property' ? 'key' : type // Properties are stored under `key`

    const columns: ColumnsType<EventOrPropType> = [
        {
            title: type,
            render: function RenderEvent(item: EventOrPropType): JSX.Element {
                return (
                    <span>
                        <span className="ph-no-capture">{item[key]}</span>
                        {item.warnings?.map((warning) => (
                            <Tooltip
                                key={warning}
                                color="orange"
                                title={
                                    <>
                                        <b>Warning!</b> {warning}
                                    </>
                                }
                            >
                                <WarningOutlined style={{ color: 'var(--warning)', marginLeft: 6 }} />
                            </Tooltip>
                        ))}
                    </span>
                )
            },
            sorter: (a: EventOrPropType, b: EventOrPropType) => ('' + a[key]).localeCompare(b[key] || ''),
            filters: [
                { text: 'Has warnings', value: 'warnings' },
                { text: 'No warnings', value: 'noWarnings' },
            ],
            onFilter: (value, record) => (value === 'warnings' ? !!record.warnings.length : !record.warnings.length),
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
                        title={`Number of queries in PostHog that included a filter on this ${type}`}
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
                    if (item[key]?.endsWith(' ')) {
                        item.warnings.push(`This ${type} ends with a space.`)
                    }
                    if (item[key]?.startsWith(' ')) {
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
                placeholder={`Filter ${type === 'property' ? 'properties' : 'events'}....`}
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
            type="info"
            showIcon
            message={`${tab} is not enabled for your instance.`}
            description={
                <>
                    You will still see the list of events and properties, but usage information will be unavailable. If
                    you want to enable event usage please set the follow environment variable:{' '}
                    <pre style={{ display: 'inline' }}>ASYNC_EVENT_PROPERTY_USAGE=1</pre>. Please note, enabling this
                    environment variable <b>may increase load considerably in your infrastructure</b>, particularly if
                    you have a large volume of events.
                </>
            }
        />
    )
}

export function EventsVolumeTable(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { preflight } = useValues(preflightLogic)

    return currentTeam?.event_names_with_usage ? (
        <>
            {preflight && !preflight?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning tab="Events Stats" />
            ) : (
                currentTeam?.event_names_with_usage[0]?.volume === null && (
                    <>
                        <Alert
                            type="warning"
                            message="We haven't been able to get usage and volume data yet. Please check back later"
                        />
                    </>
                )
            )}
            <VolumeTable data={currentTeam?.event_names_with_usage as EventOrPropType[]} type="event" />
        </>
    ) : null
}
