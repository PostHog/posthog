import React, { useState } from 'react'
import { Row, Tabs, Col, Card, Skeleton, Tag, Dropdown, Menu, Button, Popconfirm } from 'antd'
import { SessionsView } from '../sessions/SessionsView'
import { EventsTable } from 'scenes/events'
import { SessionRecordingsTable } from 'scenes/session-recordings/SessionRecordingsTable'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { PersonHeader } from './PersonHeader'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import {
    DownOutlined,
    DeleteOutlined,
    MergeCellsOutlined,
    SplitCellsOutlined,
    LoadingOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { MergePerson } from './MergePerson'
import { PersonCohorts } from './PersonCohorts'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { NewPropertyComponent } from './NewPropertyComponent'

import relativeTime from 'dayjs/plugin/relativeTime'
import { TZLabel } from 'lib/components/TimezoneAware'
import { PersonsTabType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { SplitPerson } from './SplitPerson'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
dayjs.extend(relativeTime)

const { TabPane } = Tabs

export function Person(): JSX.Element {
    const [activeCardTab, setActiveCardTab] = useState('properties')
    const [mergeModalOpen, setMergeModalOpen] = useState(false)
    const [splitModalOpen, setSplitModalOpen] = useState(false)
    const { person, personLoading, deletedPersonLoading, hasNewKeys, currentTab, showSessionRecordings, showTabs } =
        useValues(personsLogic)
    const { deletePerson, setPerson, editProperty, navigateToTab } = useActions(personsLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const ids = (
        <Menu>
            {person?.distinct_ids.map((distinct_id: string) => (
                <Menu.Item key={distinct_id}>
                    <CopyToClipboardInline explicitValue={distinct_id} iconStyle={{ color: 'var(--primary)' }}>
                        {midEllipsis(distinct_id, 32)}
                    </CopyToClipboardInline>
                </Menu.Item>
            ))}
        </Menu>
    )

    return (
        <div style={{ paddingTop: 32 }}>
            <Row gutter={16}>
                <Col span={16}>
                    {showTabs ? (
                        <Tabs
                            defaultActiveKey={PersonsTabType.EVENTS}
                            activeKey={currentTab}
                            onChange={(tab) => {
                                navigateToTab(tab as PersonsTabType)
                            }}
                        >
                            {showSessionRecordings ? (
                                <TabPane
                                    tab={<span data-attr="person-session-recordings-tab">Recordings</span>}
                                    key="sessionRecordings"
                                />
                            ) : null}
                            <TabPane tab={<span data-attr="persons-events-tab">Events</span>} key="events" />
                            {!featureFlags[FEATURE_FLAGS.REMOVE_SESSIONS] ? (
                                <TabPane tab={<span data-attr="person-sessions-tab">Sessions</span>} key="sessions" />
                            ) : null}
                        </Tabs>
                    ) : null}
                    {person && (
                        <div>
                            {currentTab === PersonsTabType.SESSION_RECORDINGS ? (
                                <>
                                    <PageHeader
                                        title="Recordings"
                                        caption="Watch recordings to see how this user interacts with your app."
                                        style={{ marginTop: 0 }}
                                    />
                                    <SessionRecordingsTable
                                        key={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                                        personUUID={person.uuid}
                                        isPersonPage
                                    />
                                </>
                            ) : currentTab === PersonsTabType.SESSIONS ? (
                                <>
                                    <PageHeader
                                        title="Sessions"
                                        caption="Explore how events are being processed within sessions."
                                        style={{ marginTop: 0 }}
                                    />
                                    <SessionsView
                                        key={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                                        personIds={person.distinct_ids}
                                        isPersonPage
                                    />
                                </>
                            ) : (
                                <EventsTable
                                    pageKey={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                                    fixedFilters={{ person_id: person.id }}
                                />
                            )}
                        </div>
                    )}
                </Col>
                <Col span={8}>
                    <Card className="card-elevated person-detail" data-test-person-details>
                        {person && (
                            <>
                                <PersonHeader person={person} />
                                <div className="item-group">
                                    <label>IDs</label>
                                    <div style={{ display: 'flex' }}>
                                        <CopyToClipboardInline
                                            explicitValue={person.distinct_ids[0]}
                                            tooltipMessage={null}
                                            iconStyle={{ color: 'var(--primary)' }}
                                            style={{ justifyContent: 'flex-end' }}
                                        >
                                            {midEllipsis(person.distinct_ids[0], 20)}
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
                                {person.created_at && (
                                    <div className="item-group">
                                        <label>First seen</label>
                                        <div>{<TZLabel time={person.created_at} />}</div>
                                    </div>
                                )}
                                <div className="text-center mt">
                                    <a onClick={() => setMergeModalOpen(true)} data-attr="merge-person-button">
                                        <MergeCellsOutlined /> Merge person
                                    </a>
                                </div>
                                {featureFlags[FEATURE_FLAGS.SPLIT_PERSON] && person.distinct_ids.length > 1 && (
                                    <div className="text-center mt">
                                        <a onClick={() => setSplitModalOpen(true)} data-attr="merge-person-button">
                                            <SplitCellsOutlined /> Split IDs into multiple people
                                        </a>
                                    </div>
                                )}
                                <div className="text-center mt">
                                    <Popconfirm
                                        title="Are you sure to delete this person and all associated data?"
                                        onConfirm={deletePerson}
                                        okText="Yes"
                                        cancelText="No"
                                    >
                                        <Button
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
                                disabled={personLoading}
                            />
                            <TabPane
                                tab={<span data-attr="persons-cohorts-tab">Cohorts</span>}
                                key="cohorts"
                                disabled={personLoading}
                            />
                        </Tabs>
                        {person &&
                            (activeCardTab == 'properties' ? (
                                <div style={{ maxWidth: '100%', overflow: 'hidden' }}>
                                    <NewPropertyComponent />
                                    <h3 className="l3">Properties list</h3>
                                    <PropertiesTable
                                        properties={person.properties}
                                        onEdit={editProperty}
                                        sortProperties={!hasNewKeys}
                                        onDelete={(key) => editProperty(key, undefined)}
                                        className="persons-page-props-table"
                                    />
                                </div>
                            ) : (
                                <PersonCohorts />
                            ))}
                        {!person && personLoading && <Skeleton paragraph={{ rows: 6 }} active />}
                    </Card>
                </Col>
            </Row>
            {mergeModalOpen && person && (
                <MergePerson person={person} onPersonChange={setPerson} closeModal={() => setMergeModalOpen(false)} />
            )}
            {splitModalOpen && person && <SplitPerson person={person} closeModal={() => setSplitModalOpen(false)} />}
        </div>
    )
}
