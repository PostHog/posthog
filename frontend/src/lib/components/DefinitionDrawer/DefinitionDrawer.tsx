import './DefinitionDrawer.scss'
import React from 'react'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { Alert, Button, Col, Collapse, Row } from 'antd'
import { Drawer } from 'lib/components/Drawer'
import { definitionDrawerLogic } from 'lib/components/DefinitionDrawer/definitionDrawerLogic'
import Title from 'antd/lib/typography/Title'
import { ObjectTags } from 'lib/components/ObjectTags'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoCircleOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { EventsTableSnippet } from 'scenes/LEGACY_events/definitions/EventsTableSnippet'
import { DefinitionDescription } from './DefinitionDescription'
import { DefinitionOwnerDropdown } from 'lib/components/DefinitionDrawer/DefinitionOwnerDropdown'

const { Panel } = Collapse

export function DefinitionDrawer(): JSX.Element {
    const { drawerState, definition, tagLoading, type, eventDefinitionTags, propertyDefinitionTags } =
        useValues(definitionDrawerLogic)
    const { closeDrawer, setNewTag, deleteTag, saveAll } = useActions(definitionDrawerLogic)
    const { preflight } = useValues(preflightLogic)
    const definitionTags = type === 'event' ? eventDefinitionTags : propertyDefinitionTags

    return (
        <>
            {definition && (
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
                            <Alert
                                type="info"
                                showIcon
                                message={`${
                                    type === 'event' ? 'Events Stats' : 'Property Stats'
                                } is not enabled for your instance.`}
                                description={
                                    <>
                                        You will still see the list of events and properties, but usage information will
                                        be unavailable. If you want to enable event usage please set the follow
                                        environment variable:{' '}
                                        <pre style={{ display: 'inline' }}>ASYNC_EVENT_PROPERTY_USAGE=1</pre>. Please
                                        note, enabling this environment variable{' '}
                                        <b>may increase load considerably in your infrastructure</b>, particularly if
                                        you have a large volume of events.
                                    </>
                                }
                            />
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

                    <Collapse style={{ paddingBottom: 32 }} defaultActiveKey={['3']} expandIconPosition="right" ghost>
                        <Panel header="Recent" key="3" className="l3 events-table">
                            <span className="text-muted" style={{ fontWeight: 400, fontSize: 14 }}>
                                Most recent events received
                            </span>
                            <EventsTableSnippet />
                        </Panel>
                    </Collapse>
                </Drawer>
            )}
        </>
    )
}
