import './SavedInsights.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconList } from '@posthog/icons'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { NewInsightShortcuts } from 'scenes/saved-insights/newInsightsMenu'
import { QuickFilterKind, SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

export * from './insightTypesMetadata'

import { isDraftInsightRow } from './draftInsight'
import { DraftInsightMoreMenu, DraftInsightNameCell } from './DraftInsightRow'
import { InsightFavoriteButton, InsightMoreMenu, useInsightsBulkSelection } from './InsightActions'
import { insightTypeMetadata } from './insightTypesMetadata'
import { NewInsightButton } from './NewInsightMenu'
import { SavedInsightListItem, savedInsightsLogic } from './savedInsightsLogic'
import { SavedInsightsRows } from './SavedInsightsRows'

export const scene: SceneExport = {
    component: SavedInsights,
    logic: savedInsightsLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function InsightIcon({
    insight,
    className,
}: {
    insight: QueryBasedInsightModel
    className?: string
}): JSX.Element | null {
    const Icon = insightTypeMetadata(insight)?.icon

    return Icon ? <Icon className={className} /> : null
}

function SavedInsightsColumns(): JSX.Element {
    const { setSavedInsightsFilters } = useActions(savedInsightsLogic)
    const { insights, insightsLoading, filters, sorting, pagination, usingFilters, draftInsightRow } =
        useValues(savedInsightsLogic)

    const summarizeInsight = useSummarizeInsight()
    const bulkSelection = useInsightsBulkSelection()

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
                        <InsightFavoriteButton insight={insight} />
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
                return <InsightMoreMenu insight={insight} />
            },
        },
    ]

    return (
        <LemonTable
            loading={insightsLoading}
            columns={columns}
            dataSource={draftInsightRow ? [draftInsightRow, ...insights.results] : insights.results}
            rowClassName={(record) => (isDraftInsightRow(record) ? 'bg-warning-highlight' : null)}
            pagination={pagination}
            noSortingCancellation
            sorting={sorting}
            onSort={(newSorting) =>
                setSavedInsightsFilters({
                    order: newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : undefined,
                })
            }
            rowKey="id"
            loadingSkeletonRows={15}
            nouns={['insight', 'insights']}
            hideSortingIndicatorWhenInactive
            emptyState={
                !insightsLoading && insights.count < 1 ? (
                    <div className="py-8">
                        <SavedInsightsEmptyState filters={filters} usingFilters={usingFilters} />
                    </div>
                ) : undefined
            }
            bulkSelection={bulkSelection}
        />
    )
}

export function SavedInsights(): JSX.Element {
    const { push } = useActions(router)
    const { setSavedInsightsFilters, setViewMode } = useActions(savedInsightsLogic)
    const { filters, viewMode } = useValues(savedInsightsLogic)

    const { tab } = filters
    const quickFilters: QuickFilterKind[] =
        tab === SavedInsightsTabs.Yours
            ? ['insightType', 'tags', 'favorites', 'featureFlags']
            : ['insightType', 'tags', 'createdBy', 'favorites', 'featureFlags']

    return (
        <SceneContent className={cn('saved-insights')}>
            <NewInsightShortcuts />
            <SceneTitleSection
                name={sceneConfigurations[Scene.SavedInsights].name}
                description={sceneConfigurations[Scene.SavedInsights].description}
                resourceType={{
                    type: sceneConfigurations[Scene.SavedInsights].iconType || 'default_icon_type',
                }}
                actions={<NewInsightButton />}
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
                    { key: SavedInsightsTabs.All, label: 'All insights' },
                    { key: SavedInsightsTabs.Yours, label: 'My insights' },
                    { key: SavedInsightsTabs.Alerts, label: 'Alerts' },
                    { key: SavedInsightsTabs.History, label: 'History' },
                ]}
                sceneInset
            />

            {tab === SavedInsightsTabs.History ? (
                <ActivityLog scope={ActivityScope.INSIGHT} />
            ) : (
                <>
                    <div className="flex items-start gap-2">
                        <div className="flex-1">
                            <SavedInsightsFilters
                                filters={filters}
                                setFilters={setSavedInsightsFilters}
                                // In the row view the filters sit in the list header instead
                                quickFilters={viewMode === 'rows' ? [] : quickFilters}
                            />
                        </div>
                        <LemonSegmentedButton
                            size="small"
                            value={viewMode}
                            onChange={setViewMode}
                            options={[
                                { value: 'rows', icon: <IconList />, tooltip: 'Show insights as rows' },
                                { value: 'table', icon: <IconTableChart />, tooltip: 'Show insights as a table' },
                            ]}
                        />
                    </div>
                    {viewMode === 'rows' ? (
                        <SavedInsightsRows quickFilters={[...quickFilters, 'sort']} />
                    ) : (
                        <SavedInsightsColumns />
                    )}
                </>
            )}
        </SceneContent>
    )
}
