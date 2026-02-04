import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconCheck } from '@posthog/icons'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumns, Sorting } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'

import { DashboardTile, QueryBasedInsightModel } from '~/types'

interface StreamlinedInsightsTableProps {
    dashboardId?: number
}

export function StreamlinedInsightsTable({ dashboardId }: StreamlinedInsightsTableProps): JSX.Element {
    const { modalPage, insights, count, insightsLoading, filters, sorting } = useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters, addInsightToDashboard, removeInsightFromDashboard } =
        useActions(addSavedInsightsModalLogic)
    const { dashboard } = useValues(dashboardLogic)
    const { dashboardUpdatesInProgress } = useValues(addSavedInsightsModalLogic)
    const summarizeInsight = useSummarizeInsight()

    // Optimistic state: track pending additions/removals
    const [optimisticState, setOptimisticState] = useState<Record<number, boolean>>({})

    // Infinite scroll: accumulate results across pages
    const [accumulatedInsights, setAccumulatedInsights] = useState<QueryBasedInsightModel[]>([])
    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const lastSearchRef = useRef<string>('')
    const lastOrderRef = useRef<string>('')

    const { search, order } = filters

    const hasMore = accumulatedInsights.length < count

    // Reset accumulated insights when search or sort changes
    useEffect(() => {
        const currentOrder = order || ''
        if (search !== lastSearchRef.current || currentOrder !== lastOrderRef.current) {
            lastSearchRef.current = search || ''
            lastOrderRef.current = currentOrder
            setAccumulatedInsights([])
            if (modalPage !== 1) {
                setModalPage(1)
            }
        }
    }, [search, order, modalPage, setModalPage])

    const handleSort = (newSorting: Sorting | null): void => {
        if (newSorting) {
            setModalFilters({ order: newSorting.order === -1 ? `-${newSorting.columnKey}` : newSorting.columnKey })
        } else if (sorting) {
            // When cancelling, cycle back to ascending on the same column
            setModalFilters({ order: sorting.columnKey })
        }
    }

    // Accumulate new results when they come in
    useEffect(() => {
        if (modalPage === 1) {
            setAccumulatedInsights(insights.results)
        } else if (insights.results.length > 0) {
            setAccumulatedInsights((prev) => {
                const existingIds = new Set(prev.map((i: QueryBasedInsightModel) => i.id))
                const newInsights = insights.results.filter((i: QueryBasedInsightModel) => !existingIds.has(i.id))
                return [...prev, ...newInsights]
            })
        }
    }, [insights.results, modalPage])

    // Infinite scroll handler
    const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current
        if (!container || insightsLoading || !hasMore) {
            return
        }

        const { scrollTop, scrollHeight, clientHeight } = container
        const scrolledToBottom = scrollTop + clientHeight >= scrollHeight - 100

        if (scrolledToBottom) {
            setModalPage(modalPage + 1)
        }
    }, [insightsLoading, hasMore, modalPage, setModalPage])

    // Clear optimistic state when actual state matches what we expected
    useEffect(() => {
        setOptimisticState((prev) => {
            const next = { ...prev }
            let changed = false
            for (const idStr of Object.keys(next)) {
                const id = Number(idStr)
                const actuallyInDashboard =
                    dashboard?.tiles.some((tile: DashboardTile) => tile.insight?.id === id) ?? false
                // Only clear if actual state matches optimistic state
                if (next[id] === actuallyInDashboard) {
                    delete next[id]
                    changed = true
                }
            }
            return changed ? next : prev
        })
    }, [dashboard?.tiles])

    const isInsightActuallyInDashboard = (insight: QueryBasedInsightModel): boolean => {
        return dashboard?.tiles.some((tile: DashboardTile) => tile.insight?.id === insight.id) ?? false
    }

    const isInsightInDashboard = (insight: QueryBasedInsightModel): boolean => {
        // Use optimistic state if available, otherwise use actual state
        if (insight.id in optimisticState) {
            return optimisticState[insight.id]
        }
        return isInsightActuallyInDashboard(insight)
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
            dataIndex: 'name',
            sorter: true,
            width: 'auto',
            render: (_, insight) => {
                const displayName = insight.name || summarizeInsight(insight.query)
                return (
                    <div className="flex flex-col gap-0.5 py-1 max-w-[450px]">
                        <Tooltip title={displayName}>
                            <span className="font-medium truncate">{insight.name || <i>{displayName}</i>}</span>
                        </Tooltip>
                        {insight.description && (
                            <span className="text-xs text-secondary truncate">{insight.description}</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Created by',
            key: 'created_by',
            width: 150,
            render: (_, insight) => {
                return insight.created_by ? (
                    <ProfilePicture user={insight.created_by} size="md" showName />
                ) : (
                    <span className="text-secondary">—</span>
                )
            },
        },
        {
            title: 'Tags',
            key: 'tags',
            width: 200,
            render: (_, insight) => {
                return insight.tags && insight.tags.length > 0 ? <ObjectTags tags={insight.tags} staticOnly /> : null
            },
        },
        {
            title: 'Last modified',
            key: 'last_modified_at',
            dataIndex: 'last_modified_at',
            sorter: true,
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
            key: 'status',
            width: 32,
            render: (_, insight) => {
                const inDashboard = isInsightInDashboard(insight)
                return inDashboard ? <IconCheck className="text-success text-xl font-bold" /> : null
            },
        },
    ]

    return (
        <div>
            <div className="mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search insights..."
                    onChange={(value) => setModalFilters({ search: value })}
                    value={search || ''}
                    fullWidth
                    autoFocus
                />
            </div>

            <div ref={scrollContainerRef} className="max-h-[400px] overflow-y-auto" onScroll={handleScroll}>
                <LemonTable
                    dataSource={accumulatedInsights}
                    columns={columns}
                    loading={insightsLoading && modalPage === 1}
                    size="small"
                    rowKey="id"
                    loadingSkeletonRows={5}
                    nouns={['insight', 'insights']}
                    sorting={sorting}
                    onSort={handleSort}
                    rowClassName={(insight) =>
                        isInsightInDashboard(insight)
                            ? 'bg-success-highlight border-l-2 border-l-success cursor-pointer'
                            : 'cursor-pointer hover:bg-surface-primary'
                    }
                    onRow={(insight) => ({
                        onClick: () => {
                            if (dashboardUpdatesInProgress[insight.id]) {
                                return
                            }
                            const currentlyIn = isInsightInDashboard(insight)
                            // Optimistically update UI immediately
                            setOptimisticState((prev) => ({ ...prev, [insight.id]: !currentlyIn }))
                            if (currentlyIn) {
                                removeInsightFromDashboard(insight, dashboardId || 0)
                            } else {
                                addInsightToDashboard(insight, dashboardId || 0)
                            }
                        },
                    })}
                    emptyState={
                        <div className="text-center py-8 text-secondary">
                            <p className="font-medium">No insights found</p>
                            <p className="text-sm">Try adjusting your search or create a new insight</p>
                        </div>
                    }
                />
                {insightsLoading && modalPage > 1 && (
                    <div className="flex justify-center py-4">
                        <Spinner className="text-2xl" />
                    </div>
                )}
            </div>
        </div>
    )
}
