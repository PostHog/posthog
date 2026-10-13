import './SavedInsights.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis, IconHeart, IconHeartFilled, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { UNFILED_DASHBOARDS_FOLDER } from 'scenes/dashboard/dashboardConstants'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { SavedInsightsEmptyState, SavedInsightsErrorState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { projectLogic } from 'scenes/projectLogic'
import { NewInsightShortcuts } from 'scenes/saved-insights/newInsightsMenu'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, ActivityScope, SavedInsightsTabs } from '~/types'

import { productAnalyticsEmptyState } from 'products/product_analytics/frontend/emptyState/productAnalyticsEmptyState'
import { HomeDashboardStarterModal } from 'products/product_analytics/frontend/insights/home/HomeDashboardStarterModal'

export * from './insightTypesMetadata'

import { ProductAnalyticsNotifications } from 'products/product_analytics/frontend/notifications/ProductAnalyticsNotifications'
import { productAnalyticsNotificationsLogic } from 'products/product_analytics/frontend/notifications/productAnalyticsNotificationsLogic'

import { isDraftInsightRow } from './draftInsight'
import { DraftInsightMoreMenu, DraftInsightNameCell } from './DraftInsightRow'
import { HomeTab } from './HomeTab'
import { InsightIcon } from './InsightIcon'
import { NewInsightButton } from './NewInsightMenu'
import { SavedInsightListItem, savedInsightsLogic } from './savedInsightsLogic'

export const scene: SceneExport = {
    component: SavedInsights,
    logic: savedInsightsLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
    emptyState: productAnalyticsEmptyState,
}

export function SavedInsights(): JSX.Element {
    const { push } = useActions(router)
    const {
        loadInsights,
        updateFavoritedInsight,
        renameInsight,
        duplicateInsight,
        setSavedInsightsFilters,
        bulkDeleteInsights,
    } = useActions(savedInsightsLogic)
    const {
        insights,
        insightsLoading,
        insightsLoadFailed,
        filters,
        sorting,
        pagination,
        usingFilters,
        bulkDeleteResponseLoading,
        draftInsightRow,
        showHomeTab,
    } = useValues(savedInsightsLogic)

    const { currentProjectId } = useValues(projectLogic)
    const { notificationCount } = useValues(productAnalyticsNotificationsLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const summarizeInsight = useSummarizeInsight()
    const dashboardChoiceLogic = sceneDashboardChoiceModalLogic({ scene: Scene.ProductAnalyticsHomeTab })
    const { isOpen: homeDashboardModalOpen, dashboardChoiceView } = useValues(dashboardChoiceLogic)
    const {
        closeSceneDashboardChoiceModal,
        setSceneDashboardChoice,
        showDashboardPicker,
        showSceneDashboardChoiceModal,
        showStarterOptions,
    } = useActions(dashboardChoiceLogic)
    const { isLoading: dashboardCreationLoading } = useValues(newDashboardLogic)
    const { addDashboard, setAsHomeTabDashboardAfterCreation, showNewDashboardModal } = useActions(newDashboardLogic)

    const { tab } = filters

    const columns: LemonTableColumns<SavedInsightListItem> = [
        {
            key: 'id',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} className="text-secondary text-2xl" />
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                if (isDraftInsightRow(insight)) {
                    return <DraftInsightNameCell item={insight} />
                }
                return (
                    <div className="flex items-center gap-1">
                        <LemonTableLink
                            to={urls.insightView(insight.short_id)}
                            title={name || <i>{summarizeInsight(insight.query)}</i>}
                            description={insight.description}
                        />
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Insight}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={insight.user_access_level}
                        >
                            <LemonButton
                                size="xsmall"
                                onClick={() => updateFavoritedInsight(insight, !insight.favorited)}
                                icon={
                                    insight.favorited ? (
                                        <IconHeartFilled className="text-danger" />
                                    ) : (
                                        <IconHeart className="text-secondary" />
                                    )
                                }
                                tooltip={`${insight.favorited ? 'Remove from' : 'Add to'} favorite insights`}
                            />
                        </AccessControlAction>
                        {insight.search_match_type === 'similar' && (
                            <span className="ml-auto">
                                <Tooltip title="Not an exact match for your search, but a close one">
                                    <LemonTag type="muted" size="small">
                                        similar
                                    </LemonTag>
                                </Tooltip>
                            </span>
                        )}
                    </div>
                )
            },
            sorter: (a, b) => (a.name || summarizeInsight(a.query)).localeCompare(b.name || summarizeInsight(b.query)),
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof SavedInsightListItem,
            key: 'tags',
            render: function renderTags(tags: string[]) {
                return <ObjectTags tags={[...tags].sort()} staticOnly />
            },
        },
        {
            title: 'Created by',
            dataIndex: 'created_by' as keyof SavedInsightListItem,
            render: function Render(_: any, item: SavedInsightListItem) {
                const { created_by } = item
                return (
                    <div className="flex flex-row items-center flex-nowrap">
                        {created_by && <ProfilePicture user={created_by} size="md" showName />}
                    </div>
                )
            },
            sorter: (a, b) =>
                (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                    b.created_by?.first_name || b.created_by?.email || ''
                ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: function RenderCreated(created_at: string) {
                return created_at ? (
                    <div className="whitespace-nowrap text-right">
                        <TZLabel time={created_at} />
                    </div>
                ) : (
                    <span className="text-secondary">—</span>
                )
            },
            align: 'right',
            defaultSortOrder: -1,
            sorter: (a, b) => dayjs(a.created_at || 0).diff(b.created_at || 0),
        },
        {
            title: 'Last modified',
            sorter: true,
            defaultSortOrder: -1,
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
        {
            title: 'Last viewed',
            sorter: true,
            defaultSortOrder: -1,
            dataIndex: 'last_viewed_at',
            render: function renderLastViewed(last_viewed_at: string | null) {
                return (
                    <div className="whitespace-nowrap">
                        {last_viewed_at ? <TZLabel time={last_viewed_at} /> : <span className="text-muted">Never</span>}
                    </div>
                )
            },
        },
        {
            width: 0,
            render: function Render(_, insight) {
                if (isDraftInsightRow(insight)) {
                    return <DraftInsightMoreMenu item={insight} />
                }
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton to={urls.insightView(insight.short_id)} fullWidth>
                                    View
                                </LemonButton>

                                <LemonDivider />

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton to={urls.insightEdit(insight.short_id)} fullWidth>
                                        Edit
                                    </LemonButton>
                                </AccessControlAction>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton
                                        onClick={() => renameInsight(insight)}
                                        data-attr={`insight-item-${insight.short_id}-dropdown-rename`}
                                        fullWidth
                                    >
                                        Rename
                                    </LemonButton>
                                </AccessControlAction>

                                <LemonButton
                                    onClick={() => duplicateInsight(insight)}
                                    data-attr="duplicate-insight-from-list-view"
                                    fullWidth
                                >
                                    Duplicate
                                </LemonButton>

                                <LemonDivider />

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Delete insight?',
                                                description:
                                                    'Are you sure you want to delete this insight? Associated alerts and subscriptions will also be removed. Their removal cannot be undone.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () =>
                                                        void deleteInsightWithUndo({
                                                            object: insight,
                                                            endpoint: `projects/${currentProjectId}/insights`,
                                                            callback: loadInsights,
                                                        }),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        }}
                                        data-attr={`insight-item-${insight.short_id}-dropdown-remove`}
                                        fullWidth
                                    >
                                        Delete insight
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    const openHomeDashboardStarter = (): void => {
        showStarterOptions()
        showSceneDashboardChoiceModal()
    }

    const createHomeDashboardWithAI = (): void => {
        if (dashboardCreationLoading) {
            return
        }
        closeSceneDashboardChoiceModal()
        setAsHomeTabDashboardAfterCreation(true, true)
        addDashboard({
            name: 'My product analytics dashboard',
            description: '',
            show: false,
            useTemplate: '',
            _create_in_folder: UNFILED_DASHBOARDS_FOLDER,
        })
    }

    const openHomeDashboardTemplates = (): void => {
        closeSceneDashboardChoiceModal()
        setAsHomeTabDashboardAfterCreation(true)
        showNewDashboardModal()
    }

    const restorePostHogHome = (): void => {
        setSceneDashboardChoice(null)
        closeSceneDashboardChoiceModal()
    }

    const homeDashboardActions =
        tab === SavedInsightsTabs.Home && showHomeTab ? (
            currentTeam?.home_tab_dashboard ? (
                <LemonMenu
                    items={[
                        {
                            label: 'Change Home dashboard',
                            onClick: openHomeDashboardStarter,
                            'data-attr': 'home-tab-choose-dashboard',
                        },
                        {
                            label: 'Use PostHog Home',
                            onClick: restorePostHogHome,
                            'data-attr': 'home-tab-restore-posthog-home',
                        },
                    ]}
                >
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconEllipsis />}
                        aria-label="Home dashboard options"
                        tooltip="Home dashboard options"
                        data-attr="home-tab-dashboard-options"
                    />
                </LemonMenu>
            ) : (
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="home-tab-choose-dashboard"
                    onClick={openHomeDashboardStarter}
                >
                    Make my own dashboard
                </LemonButton>
            )
        ) : null

    return (
        <SceneContent
            className={cn(
                'saved-insights @container/saved-insights',
                tab === SavedInsightsTabs.Home && showHomeTab && 'saved-insights--home'
            )}
        >
            <NewInsightShortcuts />
            <SceneTitleSection
                name={sceneConfigurations[Scene.SavedInsights].name}
                description={sceneConfigurations[Scene.SavedInsights].description}
                resourceType={{
                    type: sceneConfigurations[Scene.SavedInsights].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        <NewInsightButton compact={tab === SavedInsightsTabs.Home && showHomeTab} />
                        {currentTeam?.home_tab_dashboard && (
                            <div className="@min-[48rem]/saved-insights:hidden">{homeDashboardActions}</div>
                        )}
                    </>
                }
            />
            <LemonTabs
                activeKey={tab}
                onChange={(tab) => {
                    if (tab === SavedInsightsTabs.Alerts) {
                        push(urls.alerts())
                        return
                    }
                    setSavedInsightsFilters({ tab })
                }}
                tabs={[
                    ...(showHomeTab ? [{ key: SavedInsightsTabs.Home, label: 'Home' }] : []),
                    { key: SavedInsightsTabs.All, label: 'All insights' },
                    { key: SavedInsightsTabs.Yours, label: 'My insights' },
                    { key: SavedInsightsTabs.Alerts, label: 'Alerts' },
                    {
                        key: SavedInsightsTabs.Notifications,
                        label: (
                            <span className="flex items-center gap-1.5">
                                Notifications
                                {notificationCount > 0 && (
                                    <LemonTag type="completion" size="small">
                                        {notificationCount}
                                    </LemonTag>
                                )}
                            </span>
                        ),
                    },
                    { key: SavedInsightsTabs.History, label: 'History' },
                ]}
                sceneInset
                rightSlot={homeDashboardActions}
                rightSlotClassName="hidden @min-[48rem]/saved-insights:flex"
            />

            {tab === SavedInsightsTabs.Home && showHomeTab ? (
                <>
                    <HomeTab dashboardActions={homeDashboardActions} />
                    <HomeDashboardStarterModal
                        isOpen={homeDashboardModalOpen && dashboardChoiceView === 'starter'}
                        onClose={closeSceneDashboardChoiceModal}
                        onTalkToAI={createHomeDashboardWithAI}
                        onStartFromTemplate={openHomeDashboardTemplates}
                        onChooseExisting={showDashboardPicker}
                        hasCustomDashboard={!!currentTeam?.home_tab_dashboard}
                        onRestorePostHogHome={restorePostHogHome}
                        restoringPostHogHome={currentTeamLoading}
                        creatingWithAI={dashboardCreationLoading}
                        aiDisabledReason={
                            !dataProcessingAccepted &&
                            (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')
                        }
                    />
                    <SceneDashboardChoiceModal scene={Scene.ProductAnalyticsHomeTab} />
                    <NewDashboardModal redirectAfterCreation={false} />
                </>
            ) : tab === SavedInsightsTabs.Notifications ? (
                <ProductAnalyticsNotifications />
            ) : tab === SavedInsightsTabs.History ? (
                <ActivityLog scope={ActivityScope.INSIGHT} />
            ) : (
                <>
                    <SavedInsightsFilters
                        filters={filters}
                        setFilters={setSavedInsightsFilters}
                        quickFilters={
                            tab === SavedInsightsTabs.Yours ? ['insightType', 'tags', 'favorites'] : undefined
                        }
                    />
                    <LemonTable
                        loading={insightsLoading}
                        columns={columns}
                        dataSource={
                            draftInsightRow && !(insightsLoadFailed && insights.results.length < 1)
                                ? [draftInsightRow, ...insights.results]
                                : insights.results
                        }
                        rowClassName={(record) => (isDraftInsightRow(record) ? 'bg-warning-highlight' : null)}
                        pagination={pagination}
                        noSortingCancellation
                        sorting={sorting}
                        onSort={(newSorting) =>
                            setSavedInsightsFilters({
                                order: newSorting
                                    ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                    : undefined,
                            })
                        }
                        rowKey="id"
                        loadingSkeletonRows={15}
                        nouns={['insight', 'insights']}
                        hideSortingIndicatorWhenInactive
                        emptyState={
                            !insightsLoading && insightsLoadFailed && insights.results.length < 1 ? (
                                <div className="py-8">
                                    <SavedInsightsErrorState onRetry={() => loadInsights(false)} />
                                </div>
                            ) : !insightsLoading && insights.count < 1 ? (
                                <div className="py-8">
                                    <SavedInsightsEmptyState filters={filters} usingFilters={usingFilters} />
                                </div>
                            ) : undefined
                        }
                        bulkSelection={{
                            getKey: (insight: SavedInsightListItem): number => insight.id,
                            isRowSelectable: (insight: SavedInsightListItem) =>
                                isDraftInsightRow(insight)
                                    ? { disabledReason: 'This draft only exists in your browser.' }
                                    : accessLevelSatisfied(
                                            AccessControlResourceType.Insight,
                                            insight.user_access_level,
                                            AccessControlLevel.Editor
                                        )
                                      ? true
                                      : { disabledReason: "You don't have permission to edit this insight." },
                            rowAriaLabel: (insight: SavedInsightListItem) =>
                                `Select insight ${insight.name || 'Untitled'}`,
                            headerAriaLabel: 'Select all insights on this page',
                            renderActions: (ctx) => (
                                <>
                                    <BulkUpdateTagsButton
                                        resource="insights"
                                        selectedIds={ctx.selectedKeys}
                                        onSuccess={() => {
                                            ctx.clearSelection()
                                            loadInsights()
                                        }}
                                    />
                                    <LemonButton
                                        type="primary"
                                        status="danger"
                                        size="small"
                                        icon={<IconTrash />}
                                        loading={bulkDeleteResponseLoading}
                                        onClick={() => {
                                            const count = ctx.selectedCount
                                            const noun = count === 1 ? 'insight' : 'insights'
                                            LemonDialog.open({
                                                title: `Delete ${count} ${noun}?`,
                                                description: `Are you sure you want to delete ${count} ${noun}? Associated alerts and subscriptions will also be removed. Their removal cannot be undone.`,
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => {
                                                        bulkDeleteInsights({ ids: [...ctx.selectedKeys] })
                                                        ctx.clearSelection()
                                                    },
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        }}
                                    >
                                        Delete selected
                                    </LemonButton>
                                </>
                            ),
                        }}
                    />
                </>
            )}
        </SceneContent>
    )
}
