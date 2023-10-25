import { Dropdown, Menu, Tag } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { PersonDisplay } from './PersonDisplay'
import './Persons.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { MergeSplitPerson } from './MergeSplitPerson'
import { PersonCohorts } from './PersonCohorts'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { NotebookNodeType, PersonsTabType, PersonType, PropertyDefinitionType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonButton, LemonDivider, LemonSelect, Link } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { NotFound } from 'lib/components/NotFound'
import { RelatedFeatureFlags } from './RelatedFeatureFlags'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { IconInfo } from 'lib/lemon-ui/icons'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { PersonDashboard } from './PersonDashboard'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import PersonFeedCanvas from './PersonFeedCanvas'

export const scene: SceneExport = {
    component: PersonScene,
    logic: personsLogic,
    paramsToProps: ({ params: { _: rawUrlId } }): (typeof personsLogic)['props'] => ({
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
            <div>
                <span className="text-muted">Merge restrictions:</span> {person.is_identified ? 'applied' : 'none'}
                <Link
                    to={'https://posthog.com/docs/data/identify#alias-assigning-multiple-distinct-ids-to-the-same-user'}
                >
                    <Tooltip
                        title={
                            <>
                                {person.is_identified ? <strong>Cannot</strong> : 'Can'} be used as `alias_id` - click
                                for more info.
                            </>
                        }
                    >
                        <IconInfo className="ml-1 text-base shrink-0" />
                    </Tooltip>
                </Link>
            </div>
        </div>
    )
}

export function PersonScene(): JSX.Element | null {
    const {
        showCustomerSuccessDashboards,
        feedEnabled,
        person,
        personLoading,
        currentTab,
        splitMergeModalShown,
        urlId,
        distinctId,
    } = useValues(personsLogic)
    const { loadPersons, editProperty, deleteProperty, navigateToTab, setSplitMergeModalShown, setDistinctId } =
        useActions(personsLogic)
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { deletedPersonLoading } = useValues(personDeleteModalLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { currentTeam } = useValues(teamLogic)

    if (!person) {
        return personLoading ? <SpinnerOverlay sceneLevel /> : <NotFound object="Person" />
    }

    const url = urls.personByDistinctId(urlId || person.distinct_ids[0] || String(person.id))

    return (
        <>
            <PageHeader
                title={<PersonDisplay person={person} noLink withIcon={'lg'} noPopover />}
                caption={<PersonCaption person={person} />}
                notebookProps={
                    url
                        ? {
                              href: url,
                          }
                        : undefined
                }
                buttons={
                    <div className="flex gap-2">
                        <NotebookSelectButton
                            resource={{
                                attrs: {
                                    id: person?.distinct_ids[0],
                                },
                                type: NotebookNodeType.Person,
                            }}
                            type="secondary"
                        />
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

            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => {
                    navigateToTab(tab as PersonsTabType)
                }}
                data-attr="persons-tabs"
                tabs={[
                    feedEnabled
                        ? {
                              key: PersonsTabType.FEED,
                              label: <span data-attr="persons-feed-tab">Feed</span>,
                              content: <PersonFeedCanvas person={person} />,
                          }
                        : false,
                    {
                        key: PersonsTabType.PROPERTIES,
                        label: <span data-attr="persons-properties-tab">Properties</span>,
                        content: (
                            <PropertiesTable
                                type={PropertyDefinitionType.Person}
                                properties={person.properties || {}}
                                searchable
                                onEdit={editProperty}
                                sortProperties
                                embedded={false}
                                onDelete={(key) => deleteProperty(key)}
                                filterable
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.EVENTS,
                        label: <span data-attr="persons-events-tab">Events</span>,
                        content: (
                            <Query
                                query={{
                                    kind: NodeKind.DataTableNode,
                                    full: true,
                                    hiddenColumns: ['person'],
                                    source: {
                                        kind: NodeKind.EventsQuery,
                                        select: defaultDataTableColumns(NodeKind.EventsQuery),
                                        personId: person.id,
                                        after: '-24h',
                                    },
                                }}
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.SESSION_RECORDINGS,
                        label: <span data-attr="person-session-recordings-tab">Recordings</span>,
                        content: (
                            <>
                                {!currentTeam?.session_recording_opt_in ? (
                                    <div className="mb-4">
                                        <LemonBanner type="info">
                                            Session recordings are currently disabled for this project. To use this
                                            feature, please go to your{' '}
                                            <Link to={`${urls.projectSettings()}#recordings`}>project settings</Link>{' '}
                                            and enable it.
                                        </LemonBanner>
                                    </div>
                                ) : null}
                                <div className="SessionRecordingPlaylistHeightWrapper">
                                    <SessionRecordingsPlaylist personUUID={person.uuid} updateSearchParams />
                                </div>
                            </>
                        ),
                    },
                    {
                        key: PersonsTabType.COHORTS,
                        label: <span data-attr="persons-cohorts-tab">Cohorts</span>,
                        content: <PersonCohorts />,
                    },
                    groupsEnabled && person.uuid
                        ? {
                              key: PersonsTabType.RELATED,
                              label: (
                                  <span className="flex items-center" data-attr="persons-related-tab">
                                      Related groups
                                      <Tooltip title="People and groups that have shared events with this person in the last 90 days.">
                                          <IconInfo className="ml-1 text-base shrink-0" />
                                      </Tooltip>
                                  </span>
                              ),
                              content: <RelatedGroups id={person.uuid} groupTypeIndex={null} />,
                          }
                        : false,
                    person.uuid
                        ? {
                              key: PersonsTabType.FEATURE_FLAGS,
                              label: <span data-attr="persons-related-flags-tab">Feature flags</span>,
                              content: (
                                  <>
                                      <div className="flex space-x-2 items-center mb-2">
                                          <div className="flex items-center">
                                              Choose ID:
                                              <Tooltip title="Feature flags values can depend on person distincts IDs. Turn on persistence in feature flag settings if you'd like these to be constant always.">
                                                  <IconInfo className="ml-1 text-base" />
                                              </Tooltip>
                                          </div>
                                          <LemonSelect
                                              value={distinctId || person.distinct_ids[0]}
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
                                  </>
                              ),
                          }
                        : false,
                    {
                        key: PersonsTabType.HISTORY,
                        label: 'History',
                        content: (
                            <ActivityLog
                                scope={ActivityScope.PERSON}
                                id={person.id}
                                caption={
                                    <LemonBanner type="info">
                                        This page only shows changes made by users in the PostHog site. Automatic
                                        changes from the API aren't shown here.
                                    </LemonBanner>
                                }
                            />
                        ),
                    },
                    showCustomerSuccessDashboards
                        ? {
                              key: PersonsTabType.DASHBOARD,
                              label: 'Dashboard',
                              content: <PersonDashboard person={person} />,
                          }
                        : false,
                ]}
            />

            {splitMergeModalShown && person && <MergeSplitPerson person={person} />}
        </>
    )
}
