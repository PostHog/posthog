import React, { useState } from 'react'
import { Row, Tabs, Col, Card, Skeleton, Tag, Dropdown, Menu, Button, Popconfirm } from 'antd'
import { hot } from 'react-hot-loader/root'
import { SessionsTable } from '../sessions/SessionsTable'
import { EventsTable } from 'scenes/events'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { PersonHeader } from './PersonHeader'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import { DownOutlined, DeleteOutlined, MergeCellsOutlined, LoadingOutlined } from '@ant-design/icons'
import moment from 'moment'
import { MergePerson } from './MergePerson'

const { TabPane } = Tabs

export const PersonV2 = hot(_PersonV2)
function _PersonV2(): JSX.Element {
    const [activeTab, setActiveTab] = useState('events')
    const [mergeModalOpen, setMergeModalOpen] = useState(false)

    const { person, personLoading, deletedPersonLoading } = useValues(personsLogic)
    const { deletePerson, setPerson } = useActions(personsLogic)

    const ids = (
        <Menu>
            {person?.distinct_ids.map((distinct_id: string) => {
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
                                <div className="item-group">
                                    <label>First seen</label>
                                    <div>{moment(person.created_at).fromNow()}</div>
                                </div>
                                <div className="text-center mt">
                                    <a onClick={() => setMergeModalOpen(true)}>
                                        <MergeCellsOutlined /> Merge person
                                    </a>
                                </div>
                                <div className="text-center mt">
                                    <Popconfirm
                                        title="Are you sure to delete this person and all associated data?"
                                        onConfirm={deletePerson}
                                        okText="Yes"
                                        cancelText="No"
                                    >
                                        <Button
                                            onClick={() => console.log(1)}
                                            className="text-danger"
                                            disabled={deletedPersonLoading}
                                            data-attr="delete-person"
                                            type="link"
                                        >
                                            {deletedPersonLoading ? <LoadingOutlined spin /> : <DeleteOutlined />}{' '}
                                            Delete this person
                                        </Button>
                                    </Popconfirm>
                                </div>
                            </>
                        )}
                        {!person && personLoading && <Skeleton paragraph={{ rows: 4 }} active />}
                    </Card>
                </Col>
            </Row>
            {mergeModalOpen && (
                <MergePerson person={person} onPersonChange={setPerson} closeModal={() => setMergeModalOpen(false)} />
            )}
        </div>
    )
}
