import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheck, IconPlus, IconSearch } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Text,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsOwner } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { InsightModel } from '~/types'

import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'
import { InsightIcon } from './InsightIcon'
import { QuillSavedInsightsFilterMenu } from './QuillSavedInsightsFilterMenu'
import { QuillSavedInsightsPagination } from './QuillSavedInsightsPagination'
import { SavedInsightsTableProps } from './SavedInsightsTable'

const VISIBLE_TAGS = 2

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

    const hasNonSearchFilters =
        (filters.insightType !== undefined && filters.insightType !== 'All types') ||
        (filters.createdBy !== undefined && filters.createdBy !== 'All users') ||
        (filters.tags?.length ?? 0) > 0
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
                                      {selected ? 'Added' : 'Add'}
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

    const renderBody = (): JSX.Element => {
        if (!hasLoadedInsights) {
            return (
                <div aria-busy aria-label="Loading insights" className="flex flex-col gap-3 p-3">
                    {Array.from({ length: 6 }, (_, index) => (
                        <div key={index} className="flex items-center gap-3">
                            <Skeleton className="size-4 shrink-0" />
                            <Skeleton className={index % 2 === 0 ? 'h-3 w-56' : 'h-3 w-40'} />
                            <Skeleton className="ml-auto h-3 w-20" />
                        </div>
                    ))}
                </div>
            )
        }
        if (!insightsLoading && insights.count < 1) {
            const searchString = filters.search || null
            const usingFilters = !!searchString || hasNonSearchFilters
            return (
                <Empty data-attr="insight-empty-state">
                    <EmptyHeader>
                        {usingFilters && (
                            <EmptyMedia variant="icon">
                                <IconSearch />
                            </EmptyMedia>
                        )}
                        <EmptyTitle>
                            {usingFilters
                                ? searchString
                                    ? `There are no insights matching "${searchString}".`
                                    : 'There are no insights matching these filters.'
                                : 'There are no insights for this project.'}
                        </EmptyTitle>
                        <EmptyDescription>
                            {usingFilters
                                ? 'Refine your keyword search, or try using other filters such as type, last modified or created by.'
                                : 'Once you create an insight, it will show up here.'}
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent className="flex-row justify-center">
                        {hasFilteredUI && searchString && (
                            <Button variant="outline" onClick={() => setModalFilters({ search: '' })}>
                                Clear search
                            </Button>
                        )}
                        {hasFilteredUI && hasNonSearchFilters && (
                            <Button variant="outline" onClick={clearFilters}>
                                Clear filters
                            </Button>
                        )}
                        {!usingFilters && (
                            <Button
                                variant="primary"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.insightNew()} />}
                                data-attr="add-insight-button-empty-state"
                            >
                                <IconPlus />
                                New insight
                            </Button>
                        )}
                    </EmptyContent>
                </Empty>
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
                        onRowClick={
                            onToggle
                                ? (insight) => {
                                      if (!isToggling?.(insight)) {
                                          onToggle(insight)
                                      }
                                  }
                                : undefined
                        }
                        sorting={sorting ? [{ id: sorting.columnKey, desc: sorting.order === -1 }] : []}
                        onSortingChange={([sort]) =>
                            setModalFilters({ order: sort ? `${sort.desc ? '-' : ''}${sort.id}` : undefined })
                        }
                    />
                </div>
                {count > insightsPerPage && (
                    <QuillSavedInsightsPagination
                        currentPage={modalPage}
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
