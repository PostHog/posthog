import { useActions, useValues } from 'kea'

import { IconChevronDown, IconCopy, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonMenu, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { openInAdminPanel } from 'lib/utils/person-actions'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { ActivityScope, PersonType, PersonsTabType, ProductKey, PropertyDefinitionType } from '~/types'

import { MergeSplitPerson } from './MergeSplitPerson'
import { PersonCohorts } from './PersonCohorts'
import PersonFeedCanvas from './PersonFeedCanvas'
import { RelatedFeatureFlags } from './RelatedFeatureFlags'
import { PersonsLogicProps, personsLogic } from './personsLogic'

export const scene: SceneExport<PersonsLogicProps> = {
    component: PersonScene,
    logic: personsLogic,
    paramsToProps: ({ params: { _: rawUrlId } }) => ({
        syncWithUrl: true,
        urlId: decodeURIComponent(rawUrlId),
    }),
}

function PersonCaption({ person }: { person: PersonType }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <div className="flex deprecated-space-x-1">
                <div>
                    <span className="text-secondary">IDs:</span>{' '}
                    <CopyToClipboardInline
                        tooltipMessage={null}
                        description="person distinct ID"
                        style={{ justifyContent: 'flex-end' }}
                    >
                        {person.distinct_ids[0]}
                    </CopyToClipboardInline>
                </div>
                {person.distinct_ids.length > 1 && (
                    <LemonMenu
                        items={person.distinct_ids.slice(1).map((distinct_id: string) => ({
                            label: distinct_id,
                            sideIcon: <IconCopy className="text-primary-3000" />,
                            onClick: () => copyToClipboard(distinct_id, 'distinct id'),
                        }))}
                    >
                        <LemonTag type="primary" className="inline-flex">
                            <span>+{person.distinct_ids.length - 1}</span>
                            <IconChevronDown className="w-4 h-4" />
                        </LemonTag>
                    </LemonMenu>
                )}
            </div>
            <div>
                <span className="text-secondary">First seen:</span>{' '}
                {person.created_at ? <TZLabel time={person.created_at} /> : 'unknown'}
            </div>
            <div>
                <span className="text-secondary">Merge restrictions:</span> {person.is_identified ? 'applied' : 'none'}
                <Link to="https://posthog.com/docs/data/identify#alias-assigning-multiple-distinct-ids-to-the-same-user">
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
        feedEnabled,
        person,
        personLoading,
        personError,
        currentTab,
        splitMergeModalShown,
        urlId,
        distinctId,
        primaryDistinctId,
        eventsQuery,
        exceptionsQuery,
    } = useValues(personsLogic)
    const { loadPersons, editProperty, deleteProperty, navigateToTab, setSplitMergeModalShown, setDistinctId } =
        useActions(personsLogic)
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { deletedPersonLoading } = useValues(personDeleteModalLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { user } = useValues(userLogic)

    if (personError) {
        throw new Error(personError)
    }
    if (!person) {
        return personLoading ? <SpinnerOverlay sceneLevel /> : <NotFound object="person" meta={{ urlId }} />
    }

    const settingLevel = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    return (
        <SceneContent>
            <SceneTitleSection
                name="Person"
                resourceType={{
                    type: sceneConfigurations[Scene.Person].iconType || 'default_icon_type',
                }}
                forceBackTo={{
                    name: sceneConfigurations[Scene.Persons].name,
                    path: urls.persons(),
                    key: 'people',
                }}
                actions={
                    <>
                        <NotebookSelectButton
                            resource={{
                                type: NotebookNodeType.Person,
                                attrs: { distinctId: person?.distinct_ids[0] },
                            }}
                            type="secondary"
                            size="small"
                        />
                        {user?.is_staff && <OpenInAdminPanelButton />}
                        <LemonButton
                            onClick={() => showPersonDeleteModal(person, () => loadPersons())}
                            disabled={deletedPersonLoading}
                            loading={deletedPersonLoading}
                            type="secondary"
                            status="danger"
                            data-attr="delete-person"
                            size="small"
                        >
                            Delete person
                        </LemonButton>

                        {person.distinct_ids.length > 1 && (
                            <LemonButton
                                onClick={() => setSplitMergeModalShown(true)}
                                data-attr="merge-person-button"
                                type="secondary"
                                size="small"
                            >
                                Split IDs
                            </LemonButton>
                        )}
                    </>
                }
            />
            <SceneDivider />

            <PersonCaption person={person} />

            <SceneDivider />
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
                        content: <Query query={eventsQuery} />,
                    },
                    {
                        key: PersonsTabType.SESSION_RECORDINGS,
                        label: <span data-attr="person-session-recordings-tab">Recordings</span>,
                        content: (
                            <>
                                {!currentTeam?.session_recording_opt_in ? (
                                    <div className="mb-4">
                                        <LemonBanner type="info">
                                            Session recordings are currently disabled for this {settingLevel}. To use
                                            this feature, please go to your{' '}
                                            <Link
                                                to={`${urls.settings('project')}#recordings`}
                                                onClick={() => {
                                                    addProductIntentForCrossSell({
                                                        from: ProductKey.PERSONS,
                                                        to: ProductKey.SESSION_REPLAY,
                                                        intent_context: ProductIntentContext.PERSON_VIEW_RECORDINGS,
                                                    })
                                                }}
                                            >
                                                project settings
                                            </Link>{' '}
                                            and enable it.
                                        </LemonBanner>
                                    </div>
                                ) : null}
                                <div className="SessionRecordingPlaylistHeightWrapper">
                                    <SessionRecordingsPlaylist
                                        logicKey={`person-scene-${person.uuid}`}
                                        personUUID={person.uuid}
                                        distinctIds={person.distinct_ids}
                                        updateSearchParams
                                    />
                                </div>
                            </>
                        ),
                    },
                    {
                        key: PersonsTabType.EXCEPTIONS,
                        label: <span data-attr="persons-exceptions-tab">Exceptions</span>,
                        content: <Query query={exceptionsQuery} />,
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
                              tooltip: `Only shows feature flags with targeting conditions based on person properties.`,
                              label: <span data-attr="persons-related-flags-tab">Feature flags</span>,
                              content: (
                                  <>
                                      <div className="flex deprecated-space-x-2 items-center mb-2">
                                          <div className="flex items-center">
                                              Choose ID:
                                              <Tooltip
                                                  title={
                                                      <div className="deprecated-space-y-2">
                                                          <div>
                                                              Feature flags values can depend on a person's distinct ID.
                                                          </div>
                                                          <div>
                                                              If you want your flag values to stay consistent for each
                                                              user, you can enable flag persistence in the feature flag
                                                              settings.
                                                          </div>
                                                          <div>
                                                              This option may depend on your specific setup and isn't
                                                              always suitable. Read more in the{' '}
                                                              <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps">
                                                                  documentation.
                                                              </Link>
                                                          </div>
                                                      </div>
                                                  }
                                              >
                                                  <IconInfo className="ml-1 text-base" />
                                              </Tooltip>
                                          </div>
                                          <LemonSelect
                                              value={distinctId || primaryDistinctId}
                                              onChange={(value) => value && setDistinctId(value)}
                                              options={person.distinct_ids.map((distinct_id) => ({
                                                  label: distinct_id,
                                                  value: distinct_id,
                                              }))}
                                              data-attr="person-feature-flags-select"
                                          />
                                      </div>
                                      <LemonDivider className="mb-4" />
                                      <RelatedFeatureFlags distinctId={distinctId || primaryDistinctId} />
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
                ]}
            />

            {splitMergeModalShown && person && <MergeSplitPerson person={person} />}
        </SceneContent>
    )
}

function OpenInAdminPanelButton(): JSX.Element {
    const { person } = useValues(personsLogic)
    const disabledReason = !person?.properties.email ? 'Person has no email' : undefined

    return (
        <LemonButton
            type="secondary"
            onClick={() => openInAdminPanel(person?.properties.email)}
            disabledReason={disabledReason}
        >
            Open in Admin Panel
        </LemonButton>
    )
}
