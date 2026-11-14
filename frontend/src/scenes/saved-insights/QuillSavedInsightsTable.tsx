import type { ColumnDef, SortingState } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheck, IconPlus } from '@posthog/icons'
import { Badge, Button, Card, DataTable, Text, cn } from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { TZLabel } from 'lib/components/TZLabel'
import { AnalyticsOwner } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'

import { InsightModel } from '~/types'

import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'
import { InsightIcon } from './InsightIcon'
import { QuillSavedInsightsEmptyState } from './QuillSavedInsightsEmptyState'
import { QuillSavedInsightsFilterMenu } from './QuillSavedInsightsFilterMenu'
import { QuillSavedInsightsTableSkeleton } from './QuillSavedInsightsTableSkeleton'
import { SavedInsightFilters } from './savedInsightsLogic'
import { SavedInsightsTableProps } from './SavedInsightsTable'

const VISIBLE_TAGS = 2

function usesNonSearchFilters(filters: SavedInsightFilters): boolean {
    return (
        (filters.insightType !== undefined && filters.insightType !== 'All types') ||
        (filters.createdBy !== undefined && filters.createdBy !== 'All users') ||
        (filters.tags?.length ?? 0) > 0
    )
}

export function QuillSavedInsightsTable({
    isSelected,
    onToggle,
    isToggling,
    filterFn,
}: SavedInsightsTableProps): JSX.Element {
    const {
        modalPage,
        insights,
        count,
        insightsLoading,
        filters,
        sorting,
        insightsPerPage,
        hasFilteredUI,
        hasLoadedInsights,
    } = useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters } = useActions(addSavedInsightsModalLogic)
    const summarizeInsight = useSummarizeInsight()

    const hasNonSearchFilters = usesNonSearchFilters(filters)
    const clearFilters = (): void => setModalFilters({ insightType: 'All types', createdBy: 'All users', tags: [] })

    const columns = useMemo<ColumnDef<InsightModel>[]>(
        () => [
            {
                id: 'type',
                header: '',
                enableSorting: false,
                cell: ({ row }) => <InsightIcon insight={row.original} className="size-4 text-muted-foreground" />,
            },
            {
                id: 'name',
                header: 'Name',
                enableSorting: false,
                meta: { expand: true },
                cell: ({ row }) => {
                    const insight = row.original
                    const displayName = insight.name || summarizeInsight(insight.query)
                    return (
                        <div className="flex min-w-0 max-w-120 flex-col gap-0.5">
                            <Text size="xs" className="truncate font-medium" title={displayName}>
                                {insight.name || <i>{displayName}</i>}
                            </Text>
                            {insight.description && (
                                <Text size="xs" variant="muted" className="line-clamp-2" title={insight.description}>
                                    {insight.description}
                                </Text>
                            )}
                        </div>
                    )
                },
            },
            {
                id: 'tags',
                header: 'Tags',
                enableSorting: false,
                cell: ({ row }) => {
                    const tags = row.original.tags ?? []
                    if (!tags.length) {
                        return (
                            <Text size="xs" variant="muted">
                                –
                            </Text>
                        )
                    }
                    return (
                        <div className="flex items-center gap-1">
                            {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                                <Badge key={tag} className="max-w-24 truncate">
                                    {tag}
                                </Badge>
                            ))}
                            {tags.length > VISIBLE_TAGS && (
                                <Text size="xs" variant="muted" title={tags.slice(VISIBLE_TAGS).join(', ')}>
                                    {`+${tags.length - VISIBLE_TAGS}`}
                                </Text>
                            )}
                        </div>
                    )
                },
            },
            {
                id: 'created_by',
                header: 'Created by',
                enableSorting: false,
                cell: ({ row }) => <AnalyticsOwner owner={row.original.created_by} className="max-w-40" />,
            },
            {
                id: 'last_modified_at',
                accessorKey: 'last_modified_at',
                header: 'Last modified',
                sortDescFirst: true,
                cell: ({ row }) =>
                    row.original.last_modified_at ? (
                        <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
                            <TZLabel time={row.original.last_modified_at} />
                        </Text>
                    ) : null,
            },
            ...(isSelected && onToggle
                ? [
                      {
                          id: 'status',
                          header: '',
                          enableSorting: false,
                          meta: { align: 'right' as const },
                          cell: ({ row }: { row: { original: InsightModel } }) => {
                              const insight = row.original
                              const selected = isSelected(insight)
                              return (
                                  <Button
                                      size="sm"
                                      variant={selected ? 'default' : 'outline'}
                                      loading={isToggling?.(insight)}
                                      tooltip={selected ? 'Remove from dashboard' : undefined}
                                      onClick={() => onToggle(insight)}
                                      data-attr="add-insight-to-dashboard-toggle"
                                  >
                                      {selected ? <IconCheck /> : <IconPlus />}
                                      <span>{selected ? 'Added' : 'Add'}</span>
                                  </Button>
                              )
                          },
                      },
                  ]
                : []),
        ],
        [isSelected, onToggle, isToggling, summarizeInsight]
    )

    const rows = filterFn ? insights.results.filter(filterFn) : insights.results
    const searchString = filters.search || null
    const usingFilters = !!searchString || hasNonSearchFilters
    const canClearSearch = hasFilteredUI && !!searchString
    const canClearFilters = hasFilteredUI && hasNonSearchFilters
    const toggleRow = (insight: InsightModel): void => {
        if (!isToggling?.(insight)) {
            onToggle?.(insight)
        }
    }
    const tableSorting = sorting ? [{ id: sorting.columnKey, desc: sorting.order === -1 }] : []
    const onSortingChange = ([sort]: SortingState): void =>
        setModalFilters({ order: sort ? `${sort.desc ? '-' : ''}${sort.id}` : undefined })

    const renderBody = (): JSX.Element => {
        if (!hasLoadedInsights) {
            return <QuillSavedInsightsTableSkeleton />
        }
        if (!insightsLoading && insights.count < 1) {
            return (
                <QuillSavedInsightsEmptyState
                    searchString={searchString}
                    usingFilters={usingFilters}
                    onClearSearch={canClearSearch ? () => setModalFilters({ search: '' }) : undefined}
                    onClearFilters={canClearFilters ? clearFilters : undefined}
                />
            )
        }
        return (
            <Card size="sm" flush className="pt-0">
                <div className={cn('transition-opacity', insightsLoading && 'opacity-60')} aria-busy={insightsLoading}>
                    <DataTable
                        columns={columns}
                        data={rows}
                        fullWidth
                        size="sm"
                        getRowId={(insight) => String(insight.id)}
                        onRowClick={onToggle ? toggleRow : undefined}
                        sorting={tableSorting}
                        onSortingChange={onSortingChange}
                    />
                </div>
                {count > insightsPerPage && (
                    <QuillTablePagination
                        currentPage={modalPage}
                        pageCount={Math.ceil(count / insightsPerPage)}
                        pageSize={insightsPerPage}
                        total={count}
                        onPageChange={setModalPage}
                    />
                )}
            </Card>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <AnalyticsSearchInput
                    value={filters.search || ''}
                    onChange={(search) => setModalFilters({ search })}
                    label="Search for insights"
                    placeholder="Search for insights"
                    dataAttr="insight-dashboard-modal-search"
                    className="w-72 max-w-full"
                    autoFocus
                />
                {hasFilteredUI && (
                    <QuillSavedInsightsFilterMenu
                        filters={filters}
                        setFilters={setModalFilters}
                        active={hasNonSearchFilters}
                        onClear={clearFilters}
                    />
                )}
            </div>
            {renderBody()}
        </div>
    )
}
