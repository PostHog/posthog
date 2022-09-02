import React from 'react'
import { Dropdown, Menu, Tabs, Tag } from 'antd'
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
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { AlertMessage } from 'lib/components/AlertMessage'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/SessionRecordingsPlaylist'
import { RelatedFeatureFlags } from './RelatedFeatureFlags'

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
        <div className="flex flex-wrap items-center gap-2">
            <div>
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
    const { person, personLoading, deletedPersonLoading, currentTab, splitMergeModalShown, urlId } =
        useValues(personsLogic)
    const { editProperty, deleteProperty, navigateToTab, setSplitMergeModalShown, showPersonDeleteModal } =
        useActions(personsLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!person) {
        return personLoading ? (
            <SpinnerOverlay />
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
                    <div className="flex gap-2">
                        <LemonButton
                            onClick={() => showPersonDeleteModal(person)}
                            disabled={deletedPersonLoading}
                            loading={deletedPersonLoading}
                            type="secondary"
                            status="danger"
                            data-attr="delete-person"
                        >
                            Delete person
                        </LemonButton>

                        <LemonButton
                            onClick={() => setSplitMergeModalShown(true)}
                            data-attr="merge-person-button"
                            type="secondary"
                        >
                            Split or merge IDs
                        </LemonButton>
                    </div>
                }
            />

            <PersonDeleteModal />

            <Tabs
                activeKey={currentTab}
                onChange={(tab) => {
                    navigateToTab(tab as PersonsTabType)
                }}
                destroyInactiveTabPane={true}
                data-attr="persons-tabs"
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
                        sceneUrl={urls.person(urlId || person.distinct_ids[0] || String(person.id))}
                    />
                </TabPane>
                <TabPane
                    tab={<span data-attr="person-session-recordings-tab">Recordings</span>}
                    key={PersonsTabType.SESSION_RECORDINGS}
                >
                    {!currentTeam?.session_recording_opt_in ? (
                        <div className="mb-4">
                            <AlertMessage type="info">
                                Session recordings are currently disabled for this project. To use this feature, please
                                go to your <Link to={`${urls.projectSettings()}#recordings`}>project settings</Link> and
                                enable it.
                            </AlertMessage>
                        </div>
                    ) : null}
                    {featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYLIST] ? (
                        <SessionRecordingsPlaylist
                            key={person.uuid} // force refresh if user changes
                            personUUID={person.uuid}
                            isPersonPage
                        />
                    ) : (
                        <SessionRecordingsTable
                            key={person.uuid} // force refresh if user changes
                            personUUID={person.uuid}
                            isPersonPage
                        />
                    )}
                </TabPane>

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
                <TabPane tab={
                    <span data-attr="persons-related-flags-tab">
                        Feature flags
                    </span>
                }
                    key={PersonsTabType.FEATURE_FLAGS}
                >
                    <RelatedFeatureFlags id={person.uuid} />
                </TabPane>

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
