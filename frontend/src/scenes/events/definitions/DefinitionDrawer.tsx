import { useActions, useValues } from 'kea'
import { Drawer } from 'lib/components/Drawer'
import React from 'react'
import { definitionDrawerLogic } from './definitionDrawerLogic'
import Title from 'antd/es/typography/Title'
import './VolumeTable.scss'
import { Button, Collapse, Input, Select, Table, Tooltip } from 'antd'
import { ObjectTags } from 'lib/components/ObjectTags'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { Owner } from './VolumeTable'
import { humanFriendlyDetailedTime, Loading } from 'lib/utils'
import { InfoCircleOutlined } from '@ant-design/icons'
import { LineGraph } from 'scenes/insights/LineGraph'
import { LineGraphEmptyState } from 'scenes/insights/EmptyStates'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { PersonType } from '~/types'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Property } from 'lib/components/Property'

export function DefinitionDrawer(): JSX.Element {
    const { drawerState, definition, definitionLoading, type, eventDefinitionTags } = useValues(definitionDrawerLogic)
    const { closeDrawer, saveNewTag, deleteTag } = useActions(definitionDrawerLogic)
    const { Panel } = Collapse
    return (
        <>
            {definition && (
                <div className="definition-drawer">
                    <Drawer
                        placement="right"
                        headerStyle={{ paddingBottom: 0 }}
                        title={<Title level={3}>{definition.name}</Title>}
                        visible={drawerState}
                        onClose={closeDrawer}
                        width={'60vw'}
                        bodyStyle={{ padding: 14, paddingTop: 0 }}
                    >
                        <Collapse
                            defaultActiveKey={['1']}
                            expandIconPosition="right"
                            ghost
                            style={{ borderBottom: '1px solid #D9D9D9' }}
                        >
                            <Panel header="General" key="1" style={{ fontSize: 18, fontWeight: 600 }}>
                                <div className="panel-wrapper">
                                    <DefinitionDescription />
                                    <div style={{ flexDirection: 'column', paddingLeft: 14 }}>
                                        <Title level={5}>Tags</Title>
                                        <ObjectTags
                                            tags={definition.tags}
                                            onTagSave={saveNewTag}
                                            onTagDelete={deleteTag}
                                            saving={definitionLoading}
                                            tagsAvailable={eventDefinitionTags.filter(
                                                (tag) => !definition.tags.includes(tag)
                                            )}
                                        />
                                        <DefinitionOwner ownerId={definition.owner} />
                                    </div>
                                </div>
                                <div className="detail-status">
                                    <div>
                                        <Title level={5}>First seen</Title>
                                        <span>-</span>
                                    </div>
                                    <div>
                                        <Title level={5}>Last seen</Title>
                                        <span>-</span>
                                    </div>
                                    <div>
                                        <Title level={5}>Last modified</Title>
                                        <span>{humanFriendlyDetailedTime(definition.updated_at)}</span>
                                    </div>
                                    <div>
                                        <Title level={5}>Last modified by</Title>
                                        <span>{definition.updated_by?.first_name || '-'}</span>
                                    </div>
                                </div>
                            </Panel>
                        </Collapse>

                        <Collapse
                            defaultActiveKey={['3']}
                            expandIconPosition="right"
                            ghost
                            style={{ borderBottom: '1px solid #D9D9D9' }}
                        >
                            <Panel header="Usage" key="3" style={{ fontSize: 18, fontWeight: 600 }}>
                                <div className="panel-wrapper">
                                    <div style={{ paddingRight: 32 }}>
                                        <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }}>
                                            <Title level={5} style={{ marginBottom: 0 }}>
                                                Total count (30 days)
                                            </Title>
                                            <Tooltip
                                                placement="right"
                                                title="Total number of events over the last 30 days. Can be delayed by up to an hour."
                                            >
                                                <InfoCircleOutlined className="info-indicator" />
                                            </Tooltip>
                                        </div>
                                        <span>{definition.volume_30_day || '-'}</span>
                                    </div>
                                    <div>
                                        <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }}>
                                            <Title level={5}>Query Usage (30 days)</Title>
                                            <Tooltip
                                                placement="right"
                                                title={`Number of queries in PostHog that included a filter on this ${
                                                    type === 'event_definitions' ? 'event' : 'property'
                                                }`}
                                            >
                                                <InfoCircleOutlined className="info-indicator" />
                                            </Tooltip>
                                        </div>
                                        <span>{definition.query_usage_30_day || '-'}</span>
                                    </div>
                                </div>
                            </Panel>
                        </Collapse>

                        <Collapse defaultActiveKey={['3']} expandIconPosition="right" ghost>
                            <Panel
                                header="Recent"
                                key="3"
                                className="events-table"
                                style={{ fontSize: 18, fontWeight: 600 }}
                            >
                                <span className="text-muted" style={{ fontWeight: 400, fontSize: 14 }}>
                                    Most recent events received
                                </span>
                                <EventsTableSnippet />
                            </Panel>
                        </Collapse>
                    </Drawer>
                </div>
            )}
        </>
    )
}

export function DefinitionDescription(): JSX.Element {
    const { description, editing } = useValues(definitionDrawerLogic)
    const { setDescription, saveDescription, cancelDescription, setDescriptionEditing } = useActions(
        definitionDrawerLogic
    )

    return (
        <>
            <div style={{ flexDirection: 'column', minWidth: 300 }}>
                <Title level={5}>Description</Title>
                <Input.TextArea
                    style={{ minHeight: 108 }}
                    placeholder="Add description"
                    value={description || ''}
                    onChange={(e) => {
                        setDescription(e.target.value)
                        setDescriptionEditing(true)
                    }}
                />
                {editing && (
                    <>
                        <Button style={{ marginRight: 8 }} size="small" type="primary" onClick={saveDescription}>
                            Save
                        </Button>
                        <Button onClick={cancelDescription} size="small">
                            Cancel
                        </Button>
                    </>
                )}
            </div>
        </>
    )
}

export function DefinitionOwner({ ownerId }: { ownerId: number }): JSX.Element {
    const { members } = useValues(membersLogic)
    const { changeOwner } = useActions(definitionDrawerLogic)

    return (
        <div style={{ paddingTop: 16 }}>
            <Title level={5}>Owner</Title>
            <Select
                className="owner-select"
                placeholder={<Owner ownerId={ownerId} />}
                style={{ minWidth: 200 }}
                dropdownClassName="owner-option"
                onChange={(val) => changeOwner(val)}
            >
                {members.map((member) => (
                    <Select.Option key={member.user_id} value={member.user.id}>
                        <Owner user={member.user} />
                    </Select.Option>
                ))}
            </Select>
        </div>
    )
}

export function DefinitionInsight(): JSX.Element {
    const { graphResults, visibilityMap } = useValues(definitionDrawerLogic)
    const color = 'white'
    const inSharedMode = false
    return graphResults.length > 0 ? (
        graphResults.filter((result) => result.count !== 0).length > 0 ? (
            <LineGraph
                data-attr="trend-line-graph"
                type={'line'}
                color={color}
                datasets={graphResults}
                visibilityMap={visibilityMap}
                labels={(graphResults[0] && graphResults[0].labels) || []}
                isInProgress={false}
                dashboardItemId={null}
                inSharedMode={inSharedMode}
            />
        ) : (
            <LineGraphEmptyState color={color} isDashboard={false} />
        )
    ) : (
        <Loading />
    )
}

export function EventsTableSnippet(): JSX.Element {
    const { eventsSnippet } = useValues(definitionDrawerLogic)
    const columns = [
        {
            title: 'Person',
            key: 'person',
            render: function renderPerson({ person }: { person: PersonType }) {
                return person ? <PersonHeader person={person} /> : { props: { colSpan: 0 } }
            },
        },
        {
            title: 'URL',
            key: 'url',
            eventProperties: ['$current_url', '$screen_name'],
            span: 4,
            render: function renderURL({ properties }: { properties: any }) {
                return properties ? (
                    <Property
                        value={properties['$current_url'] ? properties['$current_url'] : properties['$screen_name']}
                    />
                ) : (
                    { props: { colSpan: 0 } }
                )
            },
            ellipsis: true,
        },
        {
            title: 'Source',
            key: 'source',
            render: function renderSource({ properties }: { properties: any }) {
                return properties ? <Property value={properties['$browser']} /> : { props: { colSpan: 0 } }
            },
        },
        {
            title: 'When',
            key: 'when',
            render: function renderWhen({ timestamp }: { timestamp: string }) {
                return timestamp ? <TZLabel time={timestamp} showSeconds /> : { props: { colSpan: 0 } }
            },
            ellipsis: true,
        },
    ]
    return (
        <div style={{ fontWeight: 400, paddingTop: 15 }}>
            <Table
                dataSource={eventsSnippet}
                columns={columns}
                key={'default'}
                rowKey={(row) => row.id}
                size="small"
                pagination={false}
            />
        </div>
    )
}
