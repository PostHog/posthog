import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { INSIGHTS_PER_PAGE, addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { userLogic } from 'scenes/userLogic'

import { QueryBasedInsightModel } from '~/types'

interface StreamlinedInsightsTableProps {
    dashboardId?: number
}

type QuickFilter = 'all' | 'mine'

export function StreamlinedInsightsTable({ dashboardId }: StreamlinedInsightsTableProps): JSX.Element {
    const { modalPage, insights, count, insightsLoading, filters } = useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters, addInsightToDashboard, removeInsightFromDashboard } =
        useActions(addSavedInsightsModalLogic)
    const { dashboard } = useValues(dashboardLogic)
    const { dashboardUpdatesInProgress } = useValues(addSavedInsightsModalLogic)
    const { user } = useValues(userLogic)
    const summarizeInsight = useSummarizeInsight()

    const { search, createdBy } = filters

    const currentQuickFilter: QuickFilter =
        user && createdBy !== 'All users' && Array.isArray(createdBy) && createdBy.includes(user.id) ? 'mine' : 'all'

    const handleQuickFilterChange = (value: QuickFilter): void => {
        if (value === 'mine' && user) {
            setModalFilters({ createdBy: [user.id] })
        } else {
            setModalFilters({ createdBy: 'All users' })
        }
    }

    const isInsightInDashboard = (insight: QueryBasedInsightModel): boolean => {
        return dashboard?.tiles.some((tile) => tile.insight?.id === insight.id) ?? false
    }

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            key: 'icon',
            width: 32,
            render: (_, insight) => <InsightIcon insight={insight} className="text-secondary text-xl" />,
        },
        {
            title: 'Name',
            key: 'name',
            render: (_, insight) => {
                const displayName = insight.name || summarizeInsight(insight.query)
                const inDashboard = isInsightInDashboard(insight)
                return (
                    <div className="flex flex-col gap-0.5 min-w-0 py-1">
                        <div className="flex items-center gap-2">
                            <Tooltip title={displayName}>
                                <span className="font-medium truncate">{insight.name || <i>{displayName}</i>}</span>
                            </Tooltip>
                            {inDashboard && (
                                <span className="shrink-0 text-xs text-success font-medium bg-success-highlight px-1.5 py-0.5 rounded">
                                    Added
                                </span>
                            )}
                        </div>
                        {insight.description && (
                            <span className="text-xs text-secondary truncate">{insight.description}</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Last modified',
            key: 'last_modified_at',
            width: 120,
            render: (_, insight) => {
                if (!insight.last_modified_at) {
                    return <span className="text-secondary">-</span>
                }
                const date = new Date(insight.last_modified_at)
                const now = new Date()
                const diffMs = now.getTime() - date.getTime()
                const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

                let timeAgo: string
                if (diffDays === 0) {
                    const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
                    if (diffHours === 0) {
                        const diffMins = Math.floor(diffMs / (1000 * 60))
                        timeAgo = diffMins <= 1 ? 'Just now' : `${diffMins}m ago`
                    } else {
                        timeAgo = `${diffHours}h ago`
                    }
                } else if (diffDays === 1) {
                    timeAgo = 'Yesterday'
                } else if (diffDays < 7) {
                    timeAgo = `${diffDays}d ago`
                } else {
                    timeAgo = date.toLocaleDateString()
                }

                return <span className="text-secondary text-sm whitespace-nowrap">{timeAgo}</span>
            },
        },
        {
            key: 'action',
            width: 80,
            render: (_, insight) => {
                const inDashboard = isInsightInDashboard(insight)
                const isLoading = dashboardUpdatesInProgress[insight.id]

                return (
                    <LemonButton
                        type={inDashboard ? 'secondary' : 'primary'}
                        size="small"
                        loading={isLoading}
                        icon={inDashboard ? <IconCheck /> : <IconPlus />}
                        onClick={(e) => {
                            e.preventDefault()
                            if (isLoading) {
                                return
                            }
                            if (inDashboard) {
                                removeInsightFromDashboard(insight, dashboardId || 0)
                            } else {
                                addInsightToDashboard(insight, dashboardId || 0)
                            }
                        }}
                        data-attr={inDashboard ? 'remove-insight-from-dashboard' : 'add-insight-to-dashboard'}
                    >
                        {inDashboard ? 'Added' : 'Add'}
                    </LemonButton>
                )
            },
        },
    ]

    return (
        <div>
            <div className="flex items-center gap-3 mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search insights..."
                    onChange={(value) => setModalFilters({ search: value })}
                    value={search || ''}
                    className="flex-1"
                    autoFocus
                />
                <LemonSegmentedButton
                    value={currentQuickFilter}
                    onChange={handleQuickFilterChange}
                    options={[
                        { value: 'all', label: 'All' },
                        { value: 'mine', label: 'Mine' },
                    ]}
                    size="small"
                />
            </div>

            <LemonTable
                dataSource={insights.results}
                columns={columns}
                loading={insightsLoading}
                size="small"
                pagination={{
                    controlled: true,
                    currentPage: modalPage,
                    pageSize: INSIGHTS_PER_PAGE,
                    entryCount: count,
                    onForward: () => setModalPage(modalPage + 1),
                    onBackward: () => setModalPage(modalPage - 1),
                }}
                rowKey="id"
                loadingSkeletonRows={5}
                nouns={['insight', 'insights']}
                emptyState={
                    <div className="text-center py-8 text-secondary">
                        <p className="font-medium">No insights found</p>
                        <p className="text-sm">Try adjusting your search or create a new insight</p>
                    </div>
                }
            />
        </div>
    )
}
