import React, { useState } from 'react'
import { Row, Tabs, Col, Card, Skeleton, Tag, Dropdown, Menu, Button, Popconfirm } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { EventsTable } from 'scenes/events'
import { SessionRecordingsTable } from 'scenes/session-recordings/SessionRecordingsTable'
import { useActions, useValues, BindLogic } from 'kea'
import { PersonLogicProps, personsLogic } from './personsLogic'
import { PersonHeader } from './PersonHeader'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import { DownOutlined, DeleteOutlined, MergeCellsOutlined, LoadingOutlined } from '@ant-design/icons'
import { MergeSplitPerson } from './MergeSplitPerson'
import { PersonCohorts } from './PersonCohorts'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { NewPropertyComponent } from './NewPropertyComponent'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Tooltip } from 'lib/components/Tooltip'
import { PersonsTabType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'

const { TabPane } = Tabs

export const scene: SceneExport = {
    component: Person,
    logic: personsLogic,
    paramsToProps: ({ params }) => ({ syncWithUrl: true, urlId: params._ }), // wildcard is stored in _
}

export function Person({ _: urlId }: { _?: string } = {}): JSX.Element {
    const personsLogicProps: PersonLogicProps = { syncWithUrl: true, urlId }
    const [activeCardTab, setActiveCardTab] = useState('properties')
    const {
        person,
        personLoading,
        deletedPersonLoading,
        hasNewKeys,
        currentTab,
        showSessionRecordings,
        splitMergeModalShown,
    } = useValues(personsLogic(personsLogicProps))
    const { deletePerson, editProperty, navigateToTab, setSplitMergeModalShown } = useActions(
        personsLogic(personsLogicProps)
    )
    const { showGroupsOptions } = useValues(groupsModel)

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
        <BindLogic logic={personsLogic} props={personsLogicProps}>
            <div style={{ paddingTop: 32 }}>
                <Row gutter={16}>
                    <Col span={16}>
                        {showSessionRecordings && (
                            <Tabs
                                defaultActiveKey={PersonsTabType.EVENTS}
                                activeKey={currentTab}
                                onChange={(tab) => {
                                    navigateToTab(tab as PersonsTabType)
                                }}
                            >
                                <TabPane
                                    tab={<span data-attr="person-session-recordings-tab">Recordings</span>}
                                    key="sessionRecordings"
                                />
                                <TabPane tab={<span data-attr="persons-events-tab">Events</span>} key="events" />
                            </Tabs>
                        )}
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
                                ) : (
                                    <EventsTable
                                        pageKey={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                                        fixedFilters={{ person_id: person.id }}
                                        hidePersonColumn
                                        sceneUrl={urls.person(
                                            urlId || person.distinct_ids[0] || String(person.id),
                                            false
                                        )}
                                    />
                                )}
                            </div>
                        )}
                    </Col>
                    <Col span={8}>
                        <Card className="card-elevated person-detail" data-test-person-details>
                            {person && (
                                <>
                                    <PersonHeader withIcon person={person} noLink />
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
                                        <Button
                                            type="link"
                                            onClick={() => setSplitMergeModalShown(true)}
                                            data-attr="merge-person-button"
                                        >
                                            <MergeCellsOutlined /> Split or merge IDs
                                        </Button>
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
                                {showGroupsOptions && (
                                    <TabPane
                                        tab={
                                            <span data-attr="persons-related-tab">
                                                Related groups
                                                <Tooltip
                                                    title={`Shows people and groups which have shared events with this person in the last 90 days.`}
                                                >
                                                    <InfoCircleOutlined style={{ marginLeft: 4 }} />
                                                </Tooltip>
                                            </span>
                                        }
                                        key="related"
                                        disabled={personLoading}
                                    />
                                )}
                            </Tabs>
                            {person &&
                                person.uuid &&
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
                                ) : activeCardTab == 'cohorts' ? (
                                    <PersonCohorts />
                                ) : (
                                    <RelatedGroups id={person.uuid} groupTypeIndex={null} />
                                ))}
                            {!person && personLoading && <Skeleton paragraph={{ rows: 6 }} active />}
                        </Card>
                    </Col>
                </Row>
                {splitMergeModalShown && person && <MergeSplitPerson person={person} />}
            </div>
        </BindLogic>
    )
}
