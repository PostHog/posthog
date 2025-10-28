import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { isEventFilter } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner, SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { GroupLogicProps, groupLogic } from 'scenes/groups/groupLogic'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { RelatedFeatureFlags } from 'scenes/persons/RelatedFeatureFlags'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { groupsModel } from '~/models/groupsModel'
import { Query } from '~/queries/Query/Query'
import type { ActionFilter } from '~/types'
import {
    ActivityScope,
    FilterLogicalOperator,
    GroupsTabType,
    PersonsTabType,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import GroupFeedCanvas from 'products/customer_analytics/frontend/components/GroupFeedCanvas/GroupFeedCanvas'

import { GroupOverview } from './GroupOverview'
import { RelatedGroups } from './RelatedGroups'
import { GroupNotebookCard } from './cards/GroupNotebookCard'
import { GroupCaption } from './components/GroupCaption'

export const scene: SceneExport<GroupLogicProps> = {
    component: Group,
    logic: groupLogic,
    paramsToProps: ({ params: { groupTypeIndex, groupKey } }) => ({
        groupTypeIndex: parseInt(groupTypeIndex ?? '0'),
        groupKey: decodeURIComponent(groupKey ?? ''),
    }),
}

export function Group(): JSX.Element {
    const { logicProps, groupData, groupDataLoading, groupTypeName, groupType, groupTab, groupEventsQuery } =
        useValues(groupLogic)
    const { groupKey, groupTypeIndex } = logicProps
    const { setGroupEventsQuery, editProperty, deleteProperty } = useActions(groupLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { aggregationLabel } = useValues(groupsModel)

    if (!groupData || !groupType) {
        return groupDataLoading ? <SpinnerOverlay sceneLevel /> : <NotFound object="group" />
    }

    const settingLevel = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'
    const activeTab = groupTab ?? (featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS] ? 'feed' : 'overview')

    return (
        <SceneContent>
            <SceneTitleSection
                name={groupDisplayId(groupData.group_key, groupData.group_properties)}
                resourceType={{ type: 'group' }}
                forceBackTo={{
                    name: capitalizeFirstLetter(aggregationLabel(groupTypeIndex).plural),
                    key: 'groups',
                    path: urls.groups(groupTypeIndex),
                }}
                actions={
                    <NotebookSelectButton
                        size="small"
                        type="secondary"
                        resource={{
                            type: NotebookNodeType.Group,
                            attrs: {
                                id: groupKey,
                                groupTypeIndex: groupTypeIndex,
                            },
                        }}
                    />
                }
            />
            <SceneDivider />
            <GroupCaption groupData={groupData} groupTypeName={groupTypeName} />
            <SceneDivider />
            <LemonTabs
                sceneInset
                activeKey={activeTab}
                onChange={(tab) => router.actions.push(urls.group(String(groupTypeIndex), groupKey, true, tab))}
                tabs={[
                    ...(featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]
                        ? [
                              {
                                  key: GroupsTabType.FEED,
                                  label: <span data-attr="groups-feed-tab">Feed</span>,
                                  content: <GroupFeedCanvas group={groupData} />,
                              },
                          ]
                        : []),
                    {
                        key: GroupsTabType.OVERVIEW,
                        label: <span data-attr="groups-overview-tab">Overview</span>,
                        content: <GroupOverview groupData={groupData} />,
                    },
                    ...(featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE] && groupData.notebook
                        ? [
                              {
                                  key: GroupsTabType.NOTES,
                                  label: <span data-attr="groups-notes-tab">Notes</span>,
                                  content: <GroupNotebookCard shortId={groupData.notebook} />,
                              },
                          ]
                        : []),
                    {
                        key: PersonsTabType.PROPERTIES,
                        label: <span data-attr="groups-properties-tab">Properties</span>,
                        content: (
                            <PropertiesTable
                                type={PropertyDefinitionType.Group}
                                properties={groupData.group_properties || {}}
                                embedded={false}
                                onEdit={editProperty}
                                onDelete={deleteProperty}
                                searchable
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.EVENTS,
                        label: <span data-attr="groups-events-tab">Events</span>,
                        content: groupEventsQuery ? (
                            <Query
                                query={groupEventsQuery}
                                setQuery={setGroupEventsQuery}
                                context={{ refresh: 'force_blocking' }}
                            />
                        ) : (
                            <Spinner />
                        ),
                    },
                    {
                        key: PersonsTabType.SESSION_RECORDINGS,
                        label: <span data-attr="group-session-recordings-tab">Recordings</span>,
                        content: (
                            <>
                                {!currentTeam?.session_recording_opt_in ? (
                                    <div className="mb-4">
                                        <LemonBanner type="info">
                                            Session recordings are currently disabled for this {settingLevel}. To use
                                            this feature, please go to your{' '}
                                            <Link to={`${urls.settings('project')}#recordings`}>project settings</Link>{' '}
                                            and enable it.
                                        </LemonBanner>
                                    </div>
                                ) : (
                                    <div className="SessionRecordingPlaylistHeightWrapper">
                                        <SessionRecordingsPlaylist
                                            logicKey={`groups-recordings-${groupKey}-${groupTypeIndex}`}
                                            updateSearchParams
                                            filters={{
                                                duration: [
                                                    {
                                                        type: PropertyFilterType.Recording,
                                                        key: 'duration',
                                                        value: 1,
                                                        operator: PropertyOperator.GreaterThan,
                                                    },
                                                ],
                                                filter_group: {
                                                    type: FilterLogicalOperator.And,
                                                    values: [
                                                        {
                                                            type: FilterLogicalOperator.And,
                                                            values: [
                                                                {
                                                                    type: 'events',
                                                                    name: 'All events',
                                                                    properties: [
                                                                        {
                                                                            key: `$group_${groupTypeIndex} = '${groupKey}'`,
                                                                            type: 'hogql',
                                                                        },
                                                                    ],
                                                                } as ActionFilter,
                                                            ],
                                                        },
                                                    ],
                                                },
                                            }}
                                            onFiltersChange={(filters) => {
                                                const eventFilters =
                                                    filtersFromUniversalFilterGroups(filters).filter(isEventFilter)

                                                const stillHasGroupFilter = eventFilters?.some((event) => {
                                                    return event.properties?.some(
                                                        (prop: Record<string, any>) =>
                                                            prop.key === `$group_${groupTypeIndex} = '${groupKey}'`
                                                    )
                                                })
                                                if (!stillHasGroupFilter) {
                                                    lemonToast.warning(
                                                        'Group filter removed. Please add it back to see recordings for this group.'
                                                    )
                                                }
                                            }}
                                        />
                                    </div>
                                )}
                            </>
                        ),
                    },
                    {
                        key: PersonsTabType.RELATED,
                        label: (
                            <div className="flex items-center" data-attr="group-related-tab">
                                Related people & groups
                            </div>
                        ),
                        tooltip: `People and groups that have shared events with this ${groupTypeName} in the last 90 days.`,
                        content: <RelatedGroups id={groupKey} groupTypeIndex={groupTypeIndex} />,
                    },
                    {
                        key: PersonsTabType.FEATURE_FLAGS,
                        label: <span data-attr="groups-related-flags-tab">Feature flags</span>,
                        tooltip: `Only shows feature flags with targeting conditions based on ${groupTypeName} properties.`,
                        content: (
                            <RelatedFeatureFlags
                                distinctId={groupData.group_key}
                                groupTypeIndex={groupTypeIndex}
                                groups={{ [groupType]: groupKey }}
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.HISTORY,
                        label: 'History',
                        content: (
                            <ActivityLog
                                scope={ActivityScope.GROUP}
                                id={`${groupTypeIndex}-${groupKey}`}
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
        </SceneContent>
    )
}
