import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { isEventFilter } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner, SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { groupLogic, GroupLogicProps } from 'scenes/groups/groupLogic'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { RelatedFeatureFlags } from 'scenes/persons/RelatedFeatureFlags'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import type { ActionFilter, Group } from '~/types'
import {
    ActivityScope,
    FilterLogicalOperator,
    Group as IGroup,
    NotebookNodeType,
    PersonsTabType,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { GroupPeople } from './GroupPeople'
import { GroupProperties } from './GroupProperties'
import { GroupOverviewCard } from './overview/GroupOverviewCard'
import { RelatedGroups } from './RelatedGroups'

interface GroupSceneProps {
    groupTypeIndex?: string
    groupKey?: string
}

export const scene: SceneExport = {
    component: Group,
    logic: groupLogic,
    paramsToProps: ({ params: { groupTypeIndex, groupKey } }: { params: GroupSceneProps }): GroupLogicProps => ({
        groupTypeIndex: parseInt(groupTypeIndex ?? '0'),
        groupKey: decodeURIComponent(groupKey ?? ''),
    }),
}

export function GroupCaption({ groupData, groupTypeName }: { groupData: IGroup; groupTypeName: string }): JSX.Element {
    return (
        <div className="flex items-center flex-wrap">
            <div className="mr-4">
                <span className="text-secondary">Type:</span> {groupTypeName}
            </div>
            <div className="mr-4">
                <span className="text-secondary">Key:</span>{' '}
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description="group key"
                    style={{ display: 'inline-flex', justifyContent: 'flex-end' }}
                >
                    {groupData.group_key}
                </CopyToClipboardInline>
            </div>
            <div>
                <span className="text-secondary">First seen:</span>{' '}
                {groupData.created_at ? <TZLabel time={groupData.created_at} /> : 'unknown'}
            </div>
        </div>
    )
}

function GroupOverview({ groupData }: { groupData: Group }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="col-span-1">
                    <GroupOverviewCard title="Properties">
                        <GroupProperties groupData={groupData} />
                    </GroupOverviewCard>
                </div>
                <div className="col-span-1 md:col-span-2">
                    <GroupOverviewCard title="People">
                        <GroupPeople groupData={groupData} />
                    </GroupOverviewCard>
                </div>
            </div>
            <div>
                <GroupOverviewCard title="Engagement">
                    <div className="h-64">
                        <Query
                            query={{
                                kind: NodeKind.InsightVizNode,
                                source: {
                                    kind: NodeKind.TrendsQuery,
                                    dateRange: {
                                        date_from: '-90d',
                                    },
                                    series: [
                                        {
                                            kind: NodeKind.EventsNode,
                                            math: 'total',
                                            event: null,
                                        },
                                        {
                                            kind: NodeKind.EventsNode,
                                            math: 'dau',
                                            event: null,
                                        },
                                    ],
                                },
                                embedded: true,
                            }}
                            context={{ refresh: 'force_blocking' }}
                        />
                    </div>
                </GroupOverviewCard>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="col-span-2">
                    <GroupOverviewCard title="Session recordings">
                        <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">
                            <h5 className="text-center text-sm text-secondary">There are no recordings yet</h5>
                        </div>
                    </GroupOverviewCard>
                </div>
                <div className="col-span-2">
                    <GroupOverviewCard title="Feature flags">
                        <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">
                            <RelatedFeatureFlags
                                distinctId={groupData.group_key}
                                groupTypeIndex={groupData.group_type_index}
                                groups={{ ['organization']: groupData.group_key }}
                            />
                        </div>
                    </GroupOverviewCard>
                </div>
            </div>
        </div>
    )
}

export function Group(): JSX.Element {
    const { logicProps, groupData, groupDataLoading, groupTypeName, groupType, groupTab, groupEventsQuery } =
        useValues(groupLogic)
    const { groupKey, groupTypeIndex } = logicProps
    const { setGroupEventsQuery, editProperty, deleteProperty } = useActions(groupLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!groupData || !groupType) {
        return groupDataLoading ? <SpinnerOverlay sceneLevel /> : <NotFound object="group" />
    }

    const settingLevel = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    return (
        <>
            <PageHeader
                caption={<GroupCaption groupData={groupData} groupTypeName={groupTypeName} />}
                buttons={
                    <NotebookSelectButton
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
            <LemonTabs
                activeKey={groupTab ?? PersonsTabType.PROPERTIES}
                onChange={(tab) => router.actions.push(urls.group(String(groupTypeIndex), groupKey, true, tab))}
                tabs={[
                    {
                        key: 'overview',
                        label: <span data-attr="groups-overview-tab">Overview</span>,
                        content: <GroupOverview groupData={groupData} />,
                    },
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
        </>
    )
}
