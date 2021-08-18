import { Button, Input } from 'antd'
import { InfoCircleOutlined, WarningOutlined, ArrowRightOutlined } from '@ant-design/icons'
import Table, { ColumnsType } from 'antd/lib/table'
import Fuse from 'fuse.js'
import { useValues, useActions } from 'kea'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, compactNumber } from 'lib/utils'
import React, { useState, useEffect } from 'react'
import { userLogic } from 'scenes/userLogic'
import { EventDefinition, EventOrPropType, PropertyDefinition } from '~/types'
import './VolumeTable.scss'
import { definitionDrawerLogic } from './definitions/definitionDrawerLogic'
import { ObjectTags } from 'lib/components/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Owner } from './Owner'
import { VolumeTableRecordDescription } from './definitions/VolumeTableRecordDescription'
import { Tooltip } from 'lib/components/Tooltip'

type EventTableType = 'event' | 'property'

interface VolumeTableRecord {
    eventOrProp: EventOrPropType
    warnings: string[]
}

const isPosthogEvent = (name: string): boolean => {
    return !!keyMapping.event[name]
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
    const { openDrawer } = useActions(definitionDrawerLogic)
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
                        <div style={{ display: 'flex', alignItems: 'baseline', paddingBottom: 4 }}>
                            <span className="ph-no-capture" style={{ paddingRight: 8 }}>
                                <PropertyKeyInfo
                                    style={hasTaxonomyFeatures ? { fontWeight: 'bold' } : {}}
                                    value={record.eventOrProp.name}
                                />
                            </span>
                            {hasTaxonomyFeatures ? (
                                <ObjectTags tags={record.eventOrProp.tags || []} staticOnly />
                            ) : null}
                        </div>
                        {hasTaxonomyFeatures &&
                            (isPosthogEvent(record.eventOrProp.name) ? null : (
                                <VolumeTableRecordDescription
                                    id={record.eventOrProp.id}
                                    description={record.eventOrProp.description}
                                    type={type}
                                />
                            ))}
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
                      return isPosthogEvent(record.eventOrProp.name) ? <>-</> : <Owner user={owner} />
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
                      return <span className="ph-no-capture">{compactNumber(record.eventOrProp.volume_30_day)}</span>
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
                return <span className="ph-no-capture">{compactNumber(item.eventOrProp.query_usage_30_day)}</span>
            },
            sorter: (a, b) =>
                a.eventOrProp.query_usage_30_day == b.eventOrProp.query_usage_30_day
                    ? (a.eventOrProp.query_usage_30_day || -1) - (b.eventOrProp.query_usage_30_day || -1)
                    : (a.eventOrProp.query_usage_30_day || -1) - (b.eventOrProp.query_usage_30_day || -1),
        },
        hasTaxonomyFeatures
            ? {
                  render: function Render(_, item) {
                      return (
                          <>
                              {isPosthogEvent(item.eventOrProp.name) ? null : (
                                  <Button
                                      type="link"
                                      icon={<ArrowRightOutlined style={{ color: '#5375FF' }} />}
                                      onClick={() => openDrawer(type, item.eventOrProp.id)}
                                  />
                              )}
                          </>
                      )
                  },
              }
            : {},
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
    }, [data])

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
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                onRow={(record) =>
                    hasTaxonomyFeatures && !isPosthogEvent(record.eventOrProp.name)
                        ? { onClick: () => openDrawer(type, record.eventOrProp.id), style: { cursor: 'pointer' } }
                        : {}
                }
            />
        </>
    )
}
