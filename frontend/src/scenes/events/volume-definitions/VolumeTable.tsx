import { Alert, Button, Input, Tooltip } from 'antd'
import { InfoCircleOutlined, WarningOutlined, ArrowRightOutlined } from '@ant-design/icons'
import Table, { ColumnsType } from 'antd/lib/table'
import Fuse from 'fuse.js'
import { useValues, useActions } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, humanizeNumber } from 'lib/utils'
import React, { useState, useEffect } from 'react'
import { userLogic } from 'scenes/userLogic'
import { ProfilePicture } from '~/layout/navigation/TopNavigation'
import { EventDefinition, OrganizationMemberType, PropertyDefinition, UserBasicType } from '~/types'
import { eventDefinitionsLogic } from './eventDefinitionsLogic'
import './VolumeTable.scss'
import { definitionDrawerLogic } from './definitionDrawerLogic'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'

type EventTableType = 'event' | 'property'

export type EventOrPropType = EventDefinition & PropertyDefinition

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
export function Owner({ ownerId, user }: { ownerId?: number | null, user?: UserBasicType }): JSX.Element {
    const { members } = useValues(membersLogic)
    if (!user && ownerId && members.length > 0) {
        user = members.find((mem: OrganizationMemberType) => mem.user.id === ownerId).user
    }
    return (
        <>
            {user ? (
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'row' }}>
                    <ProfilePicture name={user.first_name} email={user.email} small={true} />
                    <span style={{ paddingLeft: 8 }}>{user.first_name}</span>
                </div>
            ) : (
                <span className="text-muted" style={{ fontStyle: 'italic' }}>
                    No Owner
                </span>
            )}
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
    const { openDefinitionDrawer } = useActions(definitionDrawerLogic)
    const { members } = useValues(membersLogic)
    const hasTaxonomyFeatures = true
        // featureFlags[FEATURE_FLAGS.INGESTION_TAXONOMY] &&
        // user?.organization?.available_features?.includes('ingestion_taxonomy')

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
                      const owner = record.eventOrProp?.owner
                      return (
                         <Owner ownerId={owner} />
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
        {
            render: function Render(_, item) {
                return (
                    <Button
                        type="link"
                        icon={<ArrowRightOutlined style={{color: '#5375FF'}}/>}
                        onClick={() => openDefinitionDrawer(type, item.eventOrProp.id)}
                    />
                )
            }
        }
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
