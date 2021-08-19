import { useActions, useValues } from 'kea'
import { Drawer } from 'lib/components/Drawer'
import React from 'react'
import { definitionDrawerLogic } from './definitionDrawerLogic'
import Title from 'antd/es/typography/Title'
import '../VolumeTable.scss'
import { Alert, Button, Col, Collapse, Row } from 'antd'
import { ObjectTags } from 'lib/components/ObjectTags'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { InfoCircleOutlined } from '@ant-design/icons'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { EventPropertiesStats } from './EventPropertiesStats'
import { DefinitionOwnerDropdown } from './DefinitionOwnerDropdown'
import { DefinitionDescription } from './DefinitionDescription'
import { EventsTableSnippet } from './EventsTableSnippet'
import { UsageDisabledWarning } from '../UsageDisabledWarning'
import { Tooltip } from 'lib/components/Tooltip'

export function DefinitionDrawer(): JSX.Element {
    const { drawerState, definition, tagLoading, type, eventDefinitionTags, propertyDefinitionTags } = useValues(
        definitionDrawerLogic
    )
    const { closeDrawer, setNewTag, deleteTag, saveAll } = useActions(definitionDrawerLogic)
    const { preflight } = useValues(preflightLogic)
    const { Panel } = Collapse
    const definitionTags = type === 'event' ? eventDefinitionTags : propertyDefinitionTags

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
                        className="definition-drawer"
                        footer={
                            <Button style={{ float: 'right' }} type="primary" onClick={saveAll}>
                                Save
                            </Button>
                        }
                    >
                        {preflight && !preflight?.is_event_property_usage_enabled ? (
                            <div style={{ marginTop: 8 }}>
                                <UsageDisabledWarning tab={type === 'event' ? 'Events Stats' : 'Property Stats'} />
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
                                                    tags={definition.tags || []}
                                                    onTagSave={setNewTag}
                                                    onTagDelete={deleteTag}
                                                    saving={tagLoading}
                                                    tagsAvailable={definitionTags?.filter(
                                                        (tag) => !definition.tags?.includes(tag)
                                                    )}
                                                />
                                            </Col>
                                        </Row>
                                        {type === 'event' && (
                                            <Row>
                                                <DefinitionOwnerDropdown owner={definition.owner || null} />
                                            </Row>
                                        )}
                                    </Col>
                                </Row>
                                <Row className="detail-status">
                                    {type === 'event' && (
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
                                    )}
                                    <div style={{ textAlign: 'center' }}>
                                        <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }}>
                                            <h4 className="l4" style={{ marginBottom: 0 }}>
                                                Query Usage (30 days)
                                            </h4>
                                            <Tooltip
                                                placement="right"
                                                title={`Number of queries in PostHog that included a filter on this ${type}`}
                                            >
                                                <InfoCircleOutlined className="info-indicator" />
                                            </Tooltip>
                                        </div>
                                        <span>{definition.query_usage_30_day || '-'}</span>
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

                        {type === 'event' && (
                            <Collapse defaultActiveKey={['2']} expandIconPosition="right" ghost>
                                <Panel header="Properties" key="2" className="l3">
                                    <EventPropertiesStats />
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
