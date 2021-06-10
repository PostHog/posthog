import { useActions, useValues } from 'kea'
import { Drawer } from 'lib/components/Drawer'
import React from 'react'
import { definitionDrawerLogic } from './definitionDrawerLogic'
import Title from 'antd/es/typography/Title'
import './VolumeTable.scss'
import { Alert, Button, Col, Collapse, Input, Row, Select, Table, Tooltip } from 'antd'
import { ObjectTags } from 'lib/components/ObjectTags'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { Owner, UsageDisabledWarning } from './VolumeTable'
import { humanFriendlyDetailedTime, Loading } from 'lib/utils'
import { InfoCircleOutlined } from '@ant-design/icons'
import { LineGraph } from 'scenes/insights/LineGraph'
import { LineGraphEmptyState } from 'scenes/insights/EmptyStates'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { PersonType, UserBasicType } from '~/types'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Property } from 'lib/components/Property'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export function DefinitionDrawer(): JSX.Element {
    const { drawerState, definition, definitionLoading, type, eventDefinitionTags } = useValues(definitionDrawerLogic)
    const { closeDrawer, saveNewTag, deleteTag } = useActions(definitionDrawerLogic)
    const { preflight } = useValues(preflightLogic)
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
                        {preflight && !preflight?.is_event_property_usage_enabled ? (
                            <div style={{ marginTop: 8 }}>
                                <UsageDisabledWarning tab="Events Stats" />
                            </div>
                        ) : (
                            definition.volume_30_day === null && (
                                <>
                                    <Alert
                                        type="warning"
                                        message="We haven't been able to get usage and volume data yet. Please check later."
                                    />
                                </>
                            )
                        )}

                        <Collapse
                            defaultActiveKey={['1']}
                            expandIconPosition="right"
                            ghost
                            style={{ borderBottom: '1px solid #D9D9D9' }}
                        >
                            <Panel header="General" key="1" className="l3">
                                <Row className="panel-wrapper">
                                    <Col style={{ marginRight: 14 }}>
                                        <DefinitionDescription />
                                    </Col>
                                    <Col>
                                        <Row>
                                            <Col>
                                                <h4 className="l4">Tags</h4>
                                                <ObjectTags
                                                    tags={definition.tags}
                                                    onTagSave={saveNewTag}
                                                    onTagDelete={deleteTag}
                                                    saving={definitionLoading}
                                                    tagsAvailable={eventDefinitionTags.filter(
                                                        (tag) => !definition.tags.includes(tag)
                                                    )}
                                                />
                                            </Col>
                                        </Row>
                                        <Row>
                                            <DefinitionOwner owner={definition.owner || null} />
                                        </Row>
                                    </Col>
                                </Row>
                                <Row className="detail-status">
                                    <div>
                                        <h4 className="l4">First seen</h4>
                                        <span>-</span>
                                    </div>
                                    <div>
                                        <h4 className="l4">Last seen</h4>
                                        <span>-</span>
                                    </div>
                                    <div>
                                        <h4 className="l4">Last modified</h4>
                                        <span>{humanFriendlyDetailedTime(definition.updated_at || null)}</span>
                                    </div>
                                    <div>
                                        <h4 className="l4">Last modified by</h4>
                                        <span>{definition.updated_by?.first_name || '-'}</span>
                                    </div>
                                </Row>
                            </Panel>
                        </Collapse>

                        {preflight && preflight?.is_event_property_usage_enabled && (
                            <Collapse
                                defaultActiveKey={['3']}
                                expandIconPosition="right"
                                ghost
                                style={{ borderBottom: '1px solid #D9D9D9' }}
                            >
                                <Panel header="Usage" key="3" className="l3">
                                    <Row className="panel-wrapper">
                                        <div style={{ paddingRight: 32, textAlign: 'center' }}>
                                            <div
                                                style={{
                                                    display: 'flex',
                                                    flexDirection: 'row',
                                                    alignItems: 'center',
                                                    textAlign: 'center',
                                                }}
                                            >
                                                <h4 className="l4" style={{ marginBottom: 0 }}>
                                                    Total count (30 days)
                                                </h4>
                                                <Tooltip
                                                    placement="right"
                                                    title="Total number of events over the last 30 days. Can be delayed by up to an hour."
                                                >
                                                    <InfoCircleOutlined className="info-indicator" />
                                                </Tooltip>
                                            </div>
                                            <span>{definition.volume_30_day || '-'}</span>
                                        </div>
                                        <div style={{ textAlign: 'center' }}>
                                            <div
                                                style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }}
                                            >
                                                <h4 className="l4" style={{ marginBottom: 0 }}>
                                                    Query Usage (30 days)
                                                </h4>
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
                                    </Row>
                                </Panel>
                            </Collapse>
                        )}

                        <Collapse
                            style={{ paddingBottom: 32 }}
                            defaultActiveKey={['3']}
                            expandIconPosition="right"
                            ghost
                        >
                            <Panel header="Recent" key="3" className="l3 events-table">
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
                <h4 className="l4">Description</h4>
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

export function DefinitionOwner({ owner }: { owner: UserBasicType | null }): JSX.Element {
    const { members } = useValues(membersLogic)
    const { changeOwner } = useActions(definitionDrawerLogic)

    return (
        <div style={{ paddingTop: 16 }}>
            <h4 className="l4">Owner</h4>
            <Select
                className="owner-select"
                placeholder={<Owner user={owner} />}
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
