import { groupsLogic } from './groupsLogic'
import { PageHeader } from 'lib/components/PageHeader'
import React, { useState } from 'react'
import { Row, Tabs, Col, Card } from 'antd'
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
    const { currentGroupId, currentGroup, currentGroupType } = useValues(groupsLogic)
    const [mainActiveTab, setMainActiveTab] = useState(PersonsTabType.EVENTS)

    if (!currentGroupId) {
        return <></>
    }

    return (
        <div style={{ paddingTop: 32 }}>
            <Row gutter={16}>
                <Col span={16}>
                    <Tabs
                        defaultActiveKey={PersonsTabType.EVENTS}
                        activeKey={mainActiveTab}
                        onChange={(tab) => setMainActiveTab(tab as PersonsTabType)}
                    >
                        <TabPane tab={<span data-attr="persons-events-tab">Events</span>} key="events" />
                        <TabPane tab={<span data-attr="person-sessions-tab">Sessions</span>} key="sessions" />
                    </Tabs>
                    {currentGroup && (
                        <div>
                            {mainActiveTab === PersonsTabType.EVENTS ? (
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
                                        key={currentGroupId} // force refresh if distinct_ids change
                                        groupFilter={{
                                            group_type: `$group_${currentGroup.type_id}`,
                                            group_key: currentGroupId,
                                        }}
                                        isPersonPage
                                    />
                                </>
                            )}
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
                            </>
                        )}
                    </Card>
                    <Card className="card-elevated person-properties" style={{ marginTop: 16 }}>
                        <Tabs defaultActiveKey="properties">
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
