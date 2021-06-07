import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Alert, Button, Input, Skeleton, Table, Tooltip } from 'antd'
import Fuse from 'fuse.js'
import { InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { capitalizeFirstLetter, humanizeNumber } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { ColumnsType } from 'antd/lib/table'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { eventDefinitionsLogic } from './eventDefinitionsLogic'
import { EventDefinition, PropertyDefinition } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { userLogic } from 'scenes/userLogic'
import './VolumeTable.scss'
import { ProfilePicture } from '~/layout/navigation/TopNavigation'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
type EventTableType = 'event' | 'property'

type EventOrPropType = EventDefinition & PropertyDefinition

interface VolumeTableRecord {
    eventOrProp: EventOrPropType
    warnings: string[]
}

const search = (sources: VolumeTableRecord[], searchQuery: string): VolumeTableRecord[] => {
    return new Fuse(sources, {
        keys: ['eventOrProp.name'],
        threshold: 0.3,
    })
        .search(searchQuery)
        .map((result) => result.item)
}

export function VolumeTable({
    type,
    data,
}: {
    type: EventTableType
    data: Array<EventDefinition | PropertyDefinition>
}): JSX.Element {
    const [searchTerm, setSearchTerm] = useState(false as string | false)
    const [dataWithWarnings, setDataWithWarnings] = useState([] as VolumeTableRecord[])
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasTaxonomyFeatures =
        featureFlags[FEATURE_FLAGS.INGESTION_TAXONOMY] &&
        user?.organization?.available_features?.includes('ingestion_taxonomy')

    const columns: ColumnsType<VolumeTableRecord> = [
        {
            title: `${capitalizeFirstLetter(type)} name`,
            render: function Render(_, record): JSX.Element {
                return (
                    <span>
                        <span className="ph-no-capture">
                            <PropertyKeyInfo
                                style={hasTaxonomyFeatures ? { fontWeight: 'bold' } : {}}
                                value={record.eventOrProp.name}
                            />
                        </span>
                        {hasTaxonomyFeatures && type === 'event' && (
                            <VolumeTableRecordDescription record={record.eventOrProp} />
                        )}
                        {record.warnings?.map((warning) => (
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
            sorter: (a, b) => ('' + a.eventOrProp.name).localeCompare(b.eventOrProp.name || ''),
            filters: [
                { text: 'Has warnings', value: 'warnings' },
                { text: 'No warnings', value: 'noWarnings' },
            ],
            onFilter: (value, record) => (value === 'warnings' ? !!record.warnings.length : !record.warnings.length),
        },
        type === 'event' && hasTaxonomyFeatures
            ? {
                  title: 'Owner',
                  render: function Render(_, record): JSX.Element {
                      const owner = record.eventOrProp.owner
                      return (
                          <>
                              {owner ? (
                                  <div style={{ display: 'flex', alignItems: 'center' }}>
                                      <ProfilePicture name={owner.first_name} email={owner.email} small={true} />
                                      <span style={{ paddingLeft: 8 }}>{owner.first_name}</span>
                                  </div>
                              ) : (
                                  <span className="text-muted" style={{ fontStyle: 'italic' }}>
                                      No Owner
                                  </span>
                              )}
                          </>
                      )
                  },
              }
            : {},
        type === 'event'
            ? {
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
                  render: function RenderVolume(_, record) {
                      return <span className="ph-no-capture">{humanizeNumber(record.eventOrProp.volume_30_day)}</span>
                  },
                  sorter: (a, b) =>
                      a.eventOrProp.volume_30_day == b.eventOrProp.volume_30_day
                          ? (a.eventOrProp.volume_30_day || -1) - (b.eventOrProp.volume_30_day || -1)
                          : (a.eventOrProp.volume_30_day || -1) - (b.eventOrProp.volume_30_day || -1),
              }
            : {},
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
            render: function Render(_, item) {
                return <span className="ph-no-capture">{humanizeNumber(item.eventOrProp.query_usage_30_day)}</span>
            },
            sorter: (a, b) =>
                a.eventOrProp.query_usage_30_day == b.eventOrProp.query_usage_30_day
                    ? (a.eventOrProp.query_usage_30_day || -1) - (b.eventOrProp.query_usage_30_day || -1)
                    : (a.eventOrProp.query_usage_30_day || -1) - (b.eventOrProp.query_usage_30_day || -1),
        },
    ]

    useEffect(() => {
        setDataWithWarnings(
            data.map(
                (eventOrProp: EventOrPropType): VolumeTableRecord => {
                    const record = { eventOrProp } as VolumeTableRecord
                    record.warnings = []
                    if (eventOrProp.name?.endsWith(' ')) {
                        record.warnings.push(`This ${type} ends with a space.`)
                    }
                    if (eventOrProp.name?.startsWith(' ')) {
                        record.warnings.push(`This ${type} starts with a space.`)
                    }
                    return record
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
                dataSource={searchTerm ? search(dataWithWarnings, searchTerm) : dataWithWarnings}
                columns={columns}
                rowKey={(item) => item.eventOrProp.name}
                size="small"
                style={{ marginBottom: '4rem' }}
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
            />
        </>
    )
}

export function VolumeTableRecordDescription({
    record,
}: {
    record: EventDefinition | PropertyDefinition
}): JSX.Element {
    const [newDescription, setNewDescription] = useState(record.description)
    const [editing, setEditing] = useState(false)
    const { updateEventDefinition } = useActions(eventDefinitionsLogic)

    return (
        <div style={{ display: 'flex', minWidth: 300, marginRight: 32 }}>
            <Input.TextArea
                className="definition-description"
                placeholder="Click to add description"
                onClick={() => setEditing(true)}
                bordered={editing}
                maxLength={400}
                style={{ padding: 0, marginRight: 16, minWidth: 300 }}
                autoSize={true}
                value={newDescription || undefined}
                onChange={(e) => setNewDescription(e.target.value)}
            />
            {editing && (
                <>
                    <Button
                        style={{ marginRight: 8 }}
                        size="small"
                        type="primary"
                        onClick={() => updateEventDefinition(record.id, newDescription)}
                    >
                        Save
                    </Button>
                    <Button
                        onClick={() => {
                            setNewDescription(record.description)
                            setEditing(false)
                        }}
                        size="small"
                    >
                        Cancel
                    </Button>
                </>
            )}
        </div>
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
    const { preflight } = useValues(preflightLogic)
    const { eventDefinitions, loaded } = useValues(eventDefinitionsLogic)

    return (
        <>
            <PageHeader
                title="Events Stats"
                caption="See all event names that have ever been sent to this team, including the volume and how often
        queries where made using this event."
                style={{ marginTop: 0 }}
            />
            {loaded ? (
                <>
                    {preflight && !preflight?.is_event_property_usage_enabled ? (
                        <UsageDisabledWarning tab="Events Stats" />
                    ) : (
                        eventDefinitions[0].volume_30_day === null && (
                            <>
                                <Alert
                                    type="warning"
                                    message="We haven't been able to get usage and volume data yet. Please check back later"
                                />
                            </>
                        )
                    )}
                    <VolumeTable data={eventDefinitions} type="event" />
                </>
            ) : (
                <Skeleton active paragraph={{ rows: 5 }} />
            )}
        </>
    )
}
