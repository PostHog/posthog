import React, { useState } from 'react'
import { Row, Tabs, Col, Card, Skeleton, Tag, Dropdown, Menu } from 'antd'
import { hot } from 'react-hot-loader/root'
import { SessionsTable } from '../sessions/SessionsTable'
import { EventsTable } from 'scenes/events'
import { useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { PersonHeader } from './PersonHeader'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import { DownOutlined } from '@ant-design/icons'

const { TabPane } = Tabs

export const PersonV2 = hot(_PersonV2)
function _PersonV2(): JSX.Element {
    const [activeTab, setActiveTab] = useState('events')

    const { person, personLoading } = useValues(personsLogic)

    const ids = (
        <Menu>
            {person?.distinct_ids.map((distinct_id) => {
                return (
                    <Menu.Item key={distinct_id}>
                        <CopyToClipboardInline
                            explicitValue={distinct_id}
                            tooltipMessage=""
                            iconStyle={{ color: 'var(--primary)' }}
                        >
                            {midEllipsis(distinct_id, 32)}
                        </CopyToClipboardInline>
                    </Menu.Item>
                )
            })}
        </Menu>
    )

    return (
        <div style={{ paddingTop: 32 }}>
            <Row gutter={16}>
                <Col span={16}>
                    <Tabs
                        defaultActiveKey={activeTab}
                        onChange={(tab) => {
                            setActiveTab(tab)
                        }}
                    >
                        <TabPane tab={<span data-attr="persons-events-tab">Events</span>} key="events" />
                        <TabPane tab={<span data-attr="person-sessions-tab">Sessions</span>} key="sessions" />
                    </Tabs>
                    {person && (
                        <div>
                            {activeTab === 'events' ? (
                                <EventsTable
                                    pageKey={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                                    fixedFilters={{ person_id: person.id }}
                                />
                            ) : (
                                <SessionsTable
                                    key={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                                    personIds={person.distinct_ids}
                                    isPersonPage={true}
                                />
                            )}
                        </div>
                    )}
                </Col>
                <Col span={8}>
                    <Card className="card-elevated person-detail">
                        {person && (
                            <>
                                <PersonHeader person={person} />
                                <div className="item-group">
                                    <label>IDs</label>
                                    <div style={{ display: 'flex' }}>
                                        <CopyToClipboardInline
                                            explicitValue={person.distinct_ids[0]}
                                            tooltipMessage=""
                                            iconStyle={{ color: 'var(--primary)' }}
                                        >
                                            {midEllipsis(person.distinct_ids[0], 32)}
                                        </CopyToClipboardInline>
                                        {person.distinct_ids.length > 1 && (
                                            <Dropdown overlay={ids} trigger={['click']}>
                                                <Tag className="extra-ids">
                                                    +{person.distinct_ids.length} <DownOutlined />
                                                </Tag>
                                            </Dropdown>
                                        )}
                                    </div>
                                </div>
                            </>
                        )}
                        {!person && personLoading && <Skeleton paragraph={{ rows: 4 }} active />}
                    </Card>
                </Col>
            </Row>
        </div>
    )
}
