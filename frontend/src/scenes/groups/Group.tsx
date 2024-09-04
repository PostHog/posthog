import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
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
import { GroupDashboard } from 'scenes/groups/GroupDashboard'
import { groupLogic, GroupLogicProps } from 'scenes/groups/groupLogic'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { RelatedFeatureFlags } from 'scenes/persons/RelatedFeatureFlags'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import {
    ActionFilter,
    FilterLogicalOperator,
    Group as IGroup,
    NotebookNodeType,
    PersonsTabType,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

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
                <span className="text-muted">Type:</span> {groupTypeName}
            </div>
            <div className="mr-4">
                <span className="text-muted">Key:</span>{' '}
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description="group key"
                    style={{ display: 'inline-flex', justifyContent: 'flex-end' }}
                >
                    {groupData.group_key}
                </CopyToClipboardInline>
            </div>
            <div>
                <span className="text-muted">First seen:</span>{' '}
                {groupData.created_at ? <TZLabel time={groupData.created_at} /> : 'unknown'}
            </div>
        </div>
    )
}

export function Group(): JSX.Element {
    const {
        logicProps,
        groupData,
        groupDataLoading,
        groupTypeName,
        groupType,
        groupTab,
        groupEventsQuery,
        showCustomerSuccessDashboards,
    } = useValues(groupLogic)
    const { groupKey, groupTypeIndex } = logicProps
    const { setGroupEventsQuery } = useActions(groupLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!groupData || !groupType) {
        return groupDataLoading ? <SpinnerOverlay sceneLevel /> : <NotFound object="group" />
    }

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
                        key: PersonsTabType.PROPERTIES,
                        label: <span data-attr="groups-properties-tab">Properties</span>,
                        content: (
                            <>
                                <PropertiesTable
                                    type={PropertyDefinitionType.Group}
                                    properties={groupData.group_properties || {}}
                                    embedded={false}
                                    searchable
                                />
                                <br />

                                {featureFlags[FEATURE_FLAGS.CS_DASHBOARDS] && (
                                    <Link to={urls.groups(groupTypeIndex, 'config')}>
                                        Import properties from other sources
                                    </Link>
                                )}
                            </>
                        ),
                    },
                    {
                        key: PersonsTabType.EVENTS,
                        label: <span data-attr="groups-events-tab">Events</span>,
                        content: groupEventsQuery ? (
                            <Query
                                query={groupEventsQuery}
                                setQuery={setGroupEventsQuery}
                                context={{ alwaysRefresh: true }}
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
                                            Session recordings are currently disabled for this project. To use this
                                            feature, please go to your{' '}
                                            <Link to={`${urls.settings('project')}#recordings`}>project settings</Link>{' '}
                                            and enable it.
                                        </LemonBanner>
                                    </div>
                                ) : (
                                    <div className="SessionRecordingPlaylistHeightWrapper">
                                        <SessionRecordingsPlaylist
                                            logicKey="groups-recordings"
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
                        content: (
                            <RelatedFeatureFlags distinctId={groupData.group_key} groups={{ [groupType]: groupKey }} />
                        ),
                    },
                    showCustomerSuccessDashboards
                        ? {
                              key: PersonsTabType.DASHBOARD,
                              label: 'Dashboard',
                              content: <GroupDashboard groupData={groupData} />,
                          }
                        : null,
                ]}
            />
        </>
    )
}
