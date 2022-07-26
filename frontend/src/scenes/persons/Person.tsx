import React from 'react'
import { Button, Dropdown, Menu, Popconfirm, Tabs, Tag } from 'antd'
import { DownOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { EventsTable } from 'scenes/events'
import { SessionRecordingsTable } from 'scenes/session-recordings/SessionRecordingsTable'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { asDisplay } from './PersonHeader'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { MergeSplitPerson } from './MergeSplitPerson'
import { PersonCohorts } from './PersonCohorts'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Tooltip } from 'lib/components/Tooltip'
import { PersonsTabType, PersonType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { Loading } from 'lib/utils'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'

const { TabPane } = Tabs

export const scene: SceneExport = {
    component: Person,
    logic: personsLogic,
    paramsToProps: ({ params: { _: rawUrlId } }): typeof personsLogic['props'] => ({
        syncWithUrl: true,
        urlId: decodeURIComponent(rawUrlId),
    }),
}

function PersonCaption({ person }: { person: PersonType }): JSX.Element {
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap' }}>
            <div className="mr-4">
                <span className="text-muted">IDs:</span>{' '}
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description="person distinct ID"
                    style={{ justifyContent: 'flex-end' }}
                >
                    {person.distinct_ids[0]}
                </CopyToClipboardInline>
                {person.distinct_ids.length > 1 && (
                    <Dropdown
                        overlay={
                            <Menu>
                                {person.distinct_ids.slice(1).map((distinct_id: string) => (
                                    <Menu.Item key={distinct_id}>
                                        <CopyToClipboardInline
                                            description="person distinct ID"
                                            iconStyle={{ color: 'var(--primary)' }}
                                        >
                                            {distinct_id}
                                        </CopyToClipboardInline>
                                    </Menu.Item>
                                ))}
                            </Menu>
                        }
                        trigger={['click']}
                    >
                        <Tag className="extra-ids">
                            +{person.distinct_ids.length - 1}
                            <DownOutlined />
                        </Tag>
                    </Dropdown>
                )}
            </div>
            <div>
                <span className="text-muted">First seen:</span>{' '}
                {person.created_at ? <TZLabel time={person.created_at} /> : 'unknown'}
            </div>
        </div>
    )
}

export function Person(): JSX.Element | null {
    const {
        person,
        personLoading,
        deletedPersonLoading,
        currentTab,
        showSessionRecordings,
        splitMergeModalShown,
        urlId,
    } = useValues(personsLogic)
    const { deletePerson, editProperty, deleteProperty, navigateToTab, setSplitMergeModalShown } =
        useActions(personsLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)

    if (!person) {
        return personLoading ? (
            <Loading />
        ) : (
            <PageHeader
                title="Person not found"
                caption={urlId ? `There's no person matching distinct ID "${urlId}".` : undefined}
            />
        )
    }

    return (
        <>
            <PageHeader
                title={asDisplay(person)}
                caption={<PersonCaption person={person} />}
                buttons={
                    <div>
                        <Popconfirm
                            title="Are you sure you want to delete this person?"
                            onConfirm={deletePerson}
                            okText={`Yes, delete ${asDisplay(person)}`}
                            cancelText="No, cancel"
                        >
                            <Button
                                className="text-danger"
                                disabled={deletedPersonLoading}
                                loading={deletedPersonLoading}
                                data-attr="delete-person"
                            >
                                Delete person
                            </Button>
                        </Popconfirm>
                        <Button
                            onClick={() => setSplitMergeModalShown(true)}
                            data-attr="merge-person-button"
                            style={{ marginLeft: 8 }}
                        >
                            Split or merge IDs
                        </Button>
                    </div>
                }
            />

            <Tabs
                activeKey={currentTab}
                onChange={(tab) => {
                    navigateToTab(tab as PersonsTabType)
                }}
                destroyInactiveTabPane={true}
            >
                <TabPane
                    tab={<span data-attr="persons-properties-tab">Properties</span>}
                    key={PersonsTabType.PROPERTIES}
                >
                    <PropertiesTable
                        properties={person.properties || {}}
                        searchable
                        onEdit={editProperty}
                        sortProperties
                        embedded={false}
                        onDelete={(key) => deleteProperty(key)}
                    />
                </TabPane>
                <TabPane tab={<span data-attr="persons-events-tab">Events</span>} key={PersonsTabType.EVENTS}>
                    <EventsTable
                        pageKey={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                        fixedFilters={{ person_id: person.id }}
                        showPersonColumn={false}
                        sceneUrl={urls.person(urlId || person.distinct_ids[0] || String(person.id), false)}
                    />
                </TabPane>
                {showSessionRecordings && (
                    <TabPane
                        tab={<span data-attr="person-session-recordings-tab">Recordings</span>}
                        key={PersonsTabType.SESSION_RECORDINGS}
                    >
                        <SessionRecordingsTable
                            key={person.uuid} // force refresh if user changes
                            personUUID={person.uuid}
                            isPersonPage
                        />
                    </TabPane>
                )}

                <TabPane tab={<span data-attr="persons-cohorts-tab">Cohorts</span>} key={PersonsTabType.COHORTS}>
                    <PersonCohorts />
                </TabPane>
                {groupsEnabled && person.uuid && (
                    <TabPane
                        tab={
                            <span data-attr="persons-related-tab">
                                Related groups
                                <Tooltip title="People and groups that have shared events with this person in the last 90 days.">
                                    <InfoCircleOutlined style={{ marginLeft: 6, marginRight: 0 }} />
                                </Tooltip>
                            </span>
                        }
                        key={PersonsTabType.RELATED}
                    >
                        <RelatedGroups id={person.uuid} groupTypeIndex={null} />
                    </TabPane>
                )}

                <TabPane tab="History" key="history">
                    <ActivityLog
                        scope={ActivityScope.PERSON}
                        id={person.id}
                        describer={personActivityDescriber}
                        caption={
                            <div>
                                <InfoCircleOutlined style={{ marginRight: '.25rem' }} />
                                <span>
                                    This page only shows changes made by users in the PostHog site. Automatic changes
                                    from the API aren't shown here.
                                </span>
                            </div>
                        }
                    />
                </TabPane>
            </Tabs>

            {splitMergeModalShown && person && <MergeSplitPerson person={person} />}
        </>
    )
}
