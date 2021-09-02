import { groupsLogic } from './groupsLogic'
import { PageHeader } from 'lib/components/PageHeader'
import React, { useState } from 'react'
import { Row, Tabs, Col, Card, Button, Popconfirm } from 'antd'
import { SessionsView } from '../sessions/SessionsView'
import { EventsTable } from 'scenes/events'
import { useValues } from 'kea'
import './../persons/Persons.scss'
import dayjs from 'dayjs'
import { PropertiesTable } from 'lib/components/PropertiesTable'

import relativeTime from 'dayjs/plugin/relativeTime'
import { TZLabel } from 'lib/components/TimezoneAware'
import { PersonsTabType } from '~/types'

dayjs.extend(relativeTime)

const { TabPane } = Tabs

export function Group(): JSX.Element {
    const [activeCardTab, setActiveCardTab] = useState('properties')

    const { currentGroupId, currentGroup, currentGroupType } = useValues(groupsLogic)

    return (
        <div style={{ paddingTop: 32 }}>
            <Row gutter={16}>
                <Col span={16}>
                    <Tabs defaultActiveKey={PersonsTabType.EVENTS} activeKey={PersonsTabType.EVENTS}>
                        <TabPane tab={<span data-attr="persons-events-tab">Events</span>} key="events" />
                        <TabPane tab={<span data-attr="person-sessions-tab">Sessions</span>} key="sessions" />
                    </Tabs>
                    {currentGroup && (
                        <div>
                            {
                                /* activeTab === 'events' */ true ? (
                                    <EventsTable
                                        pageKey={'017ba52f-9638-0027-f71a-0411e70eaaa8'} // force refresh if distinct_ids change
                                        fixedFilters={{
                                            group: JSON.stringify({
                                                group_type: `$group_${currentGroup.type_id}`,
                                                group_key: currentGroupId,
                                            }),
                                        }}
                                    />
                                ) : (
                                    <>
                                        <PageHeader
                                            title="Sessions"
                                            caption="Explore how events are being processed within sessions."
                                            style={{ marginTop: 0 }}
                                        />
                                        <SessionsView
                                            key={'017ba52f-9638-0027-f71a-0411e70eaaa8'} // force refresh if distinct_ids change
                                            personIds={['017ba52f-9638-0027-f71a-0411e70eaaa8']}
                                            isPersonPage
                                        />
                                    </>
                                )
                            }
                        </div>
                    )}
                </Col>
                <Col span={8}>
                    <Card className="card-elevated person-detail" data-test-person-details>
                        {currentGroup && (
                            <>
                                <div className="item-group">
                                    <h3>{currentGroupId}</h3>
                                    <h5>
                                        <code>{currentGroupType}</code>
                                    </h5>
                                </div>

                                {currentGroup.created_at && (
                                    <div className="item-group">
                                        <label>First seen</label>
                                        <div>{<TZLabel time={currentGroup.created_at} />}</div>
                                    </div>
                                )}
                                <div className="text-center mt">
                                    <Popconfirm
                                        title="Are you sure to delete this person and all associated data?"
                                        onConfirm={() => {}}
                                        okText="Yes"
                                        cancelText="No"
                                    >
                                        <Button
                                            className="text-danger"
                                            disabled={true}
                                            data-attr="delete-person"
                                            type="link"
                                        >
                                            Delete this group
                                        </Button>
                                    </Popconfirm>
                                </div>
                            </>
                        )}
                    </Card>
                    <Card className="card-elevated person-properties" style={{ marginTop: 16 }}>
                        <Tabs
                            defaultActiveKey={activeCardTab}
                            onChange={(tab) => {
                                setActiveCardTab(tab)
                            }}
                        >
                            <TabPane
                                tab={<span data-attr="persons-properties-tab">Properties</span>}
                                key="properties"
                            />
                        </Tabs>
                        {currentGroup && (
                            <div style={{ maxWidth: '100%', overflow: 'hidden' }}>
                                <PropertiesTable
                                    properties={currentGroup.properties}
                                    sortProperties={true}
                                    className="persons-page-props-table"
                                />
                            </div>
                        )}
                    </Card>
                </Col>
            </Row>
        </div>
    )
}
