import { Dropdown, Menu, Tabs, Tag } from 'antd'
import { DownOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { EventsTable } from 'scenes/events'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { asDisplay } from './PersonHeader'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { MergeSplitPerson } from './MergeSplitPerson'
import { PersonCohorts } from './PersonCohorts'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/components/Tooltip'
import { PersonsTabType, PersonType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonButton, LemonDivider, LemonSelect, Link } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { AlertMessage } from 'lib/components/AlertMessage'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { NotFound } from 'lib/components/NotFound'
import { RelatedFeatureFlags } from './RelatedFeatureFlags'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'
import { DEFAULT_PERSON_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'

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
    const { person, personLoading, currentTab, splitMergeModalShown, urlId, distinctId } = useValues(personsLogic)
    const { loadPersons, editProperty, deleteProperty, navigateToTab, setSplitMergeModalShown, setDistinctId } =
        useActions(personsLogic)
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { deletedPersonLoading } = useValues(personDeleteModalLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]

    if (!person) {
        return personLoading ? <SpinnerOverlay /> : <NotFound object="Person" />
    }

    return (
        <>
            <PageHeader
                title={asDisplay(person)}
                caption={<PersonCaption person={person} />}
                buttons={
                    <div className="flex gap-2">
                        <LemonButton
                            onClick={() => showPersonDeleteModal(person, () => loadPersons())}
                            disabled={deletedPersonLoading}
                            loading={deletedPersonLoading}
                            type="secondary"
                            status="danger"
                            data-attr="delete-person"
                        >
                            Delete person
                        </LemonButton>

                        {person.distinct_ids.length > 1 && (
                            <LemonButton
                                onClick={() => setSplitMergeModalShown(true)}
                                data-attr="merge-person-button"
                                type="secondary"
                            >
                                Split IDs
                            </LemonButton>
                        )}
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
                    {featureDataExploration ? (
                        <Query
                            query={{
                                kind: NodeKind.DataTableNode,
                                hiddenColumns: ['person'],
                                source: {
                                    kind: NodeKind.EventsNode,
                                    personId: person.id,
                                },
                                showReload: true,
                                showColumnConfigurator: true,
                                showExport: true,
                                showEventFilter: true,
                                showPropertyFilter: true,
                            }}
                        />
                    ) : (
                        <EventsTable
                            pageKey={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                            fixedFilters={{ person_id: person.id }}
                            showPersonColumn={false}
                            sceneUrl={urls.person(urlId || person.distinct_ids[0] || String(person.id))}
                        />
                    )}
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
                    <SessionRecordingsPlaylist
                        personUUID={person.uuid}
                        updateSearchParams
                        filters={DEFAULT_PERSON_RECORDING_FILTERS}
                    />
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
                {person.uuid && (
                    <TabPane
                        tab={<span data-attr="persons-related-flags-tab">Feature flags</span>}
                        key={PersonsTabType.FEATURE_FLAGS}
                    >
                        <div className="flex space-x-4 items-center mb-2">
                            <div>
                                Choose ID:
                                <Tooltip title="Feature flags can have different values based on the persons IDs. Turn on persistence in feature flag settings if you'd like these to be constant always.">
                                    <InfoCircleOutlined style={{ marginLeft: 6, marginRight: 0 }} />
                                </Tooltip>
                            </div>
                            <LemonSelect
                                value={person.distinct_ids[0]}
                                onChange={(value) => value && setDistinctId(value)}
                                options={person.distinct_ids.map((distinct_id) => ({
                                    label: distinct_id,
                                    value: distinct_id,
                                }))}
                                data-attr="person-feature-flags-select"
                            />
                        </div>
                        <LemonDivider className="mb-4" />
                        <RelatedFeatureFlags distinctId={distinctId || person.distinct_ids[0]} />
                    </TabPane>
                )}

                <TabPane tab="History" key="history">
                    <ActivityLog
                        scope={ActivityScope.PERSON}
                        id={person.id}
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
