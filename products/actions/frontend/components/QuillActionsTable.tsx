import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPin, IconPinFilled } from '@posthog/icons'
import {
    Button,
    Card,
    DataTable,
    DataTableProps,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { QuillTagsCell } from 'lib/components/QuillTagsCell/QuillTagsCell'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsOwner } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { ActionType } from '~/types'

import { ACTIONS_PER_PAGE, actionsLogic } from '../logics/actionsLogic'
import { ActionStepConditions, ActionStepSummary } from '../utils/actionStepDescription'
import { deleteActionWithWarning } from '../utils/deleteAction'
import { EventHealthWarning } from './EventHealthWarning'
import { QuillActionRowMenu } from './QuillActionRowMenu'
import { QuillActionsEmptyState } from './QuillActionsEmptyState'
import { QuillActionsFilterMenu } from './QuillActionsFilterMenu'
import { QuillDeleteReferencedActionDialog } from './QuillDeleteReferencedActionDialog'

const DEFAULT_ORDERING = '-created_by'

type Columns = DataTableProps<ActionType, unknown>['columns']
type SortingState = NonNullable<DataTableProps<ActionType, unknown>['sorting']>

interface PendingDelete {
    referenceCount: number
    performDelete: () => Promise<void>
}

export function QuillActionsTable(): JSX.Element {
    const {
        actionsList,
        actionCount,
        actionsResponseLoading,
        hasLoadedActions,
        actionsLoadFailed,
        hasActiveFilters,
        page,
        filters,
        searchTerm,
    } = useValues(actionsLogic)
    const { setSearchTerm, setFilters, setPage, pinAction, unpinAction, loadActions, reloadAfterDelete } =
        useActions(actionsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null)

    const columns = useMemo<Columns>(() => {
        const deleteAction = (action: ActionType): void => {
            if (currentProjectId === null) {
                return
            }
            void deleteActionWithWarning(currentProjectId, action, reloadAfterDelete, (referenceCount, performDelete) =>
                setPendingDelete({ referenceCount, performDelete })
            )
        }

        return [
            {
                id: 'pinned_at',
                accessorKey: 'pinned_at',
                header: 'Pinned',
                sortDescFirst: true,
                enableResizing: false,
                cell: ({ row }) => {
                    const action = row.original
                    const pinned = !!action.pinned_at
                    return (
                        <Button
                            variant="default"
                            size="icon-sm"
                            tooltip={pinned ? 'Unpin action' : 'Pin action'}
                            aria-label={pinned ? 'Unpin action' : 'Pin action'}
                            onClick={() => (pinned ? unpinAction(action) : pinAction(action))}
                        >
                            {pinned ? <IconPinFilled /> : <IconPin />}
                        </Button>
                    )
                },
            },
            {
                id: 'name',
                accessorKey: 'name',
                header: 'Name',
                minSize: 256,
                meta: { expand: true },
                cell: ({ row }) => {
                    const action = row.original
                    return (
                        <div className="flex min-w-0 flex-col items-start gap-0.5">
                            <Button
                                variant="link-foreground"
                                size="inline"
                                nativeButton={false}
                                left
                                render={<LinkPrimitive to={urls.action(action.id)} />}
                                className="min-w-0 max-w-full"
                                data-attr={'action-link-' + row.index}
                            >
                                <span className="truncate">{action.name || <i>Unnamed</i>}</span>
                            </Button>
                            {action.description && (
                                <Text size="xs" variant="muted" className="line-clamp-2" title={action.description}>
                                    {action.description}
                                </Text>
                            )}
                        </div>
                    )
                },
            },
            {
                id: 'type',
                header: 'Type',
                enableSorting: false,
                cell: ({ row }) => {
                    const steps = row.original.steps ?? []
                    if (!steps.length) {
                        return (
                            <Text size="xs" variant="muted" className="italic">
                                Empty – set this action up
                            </Text>
                        )
                    }
                    return (
                        <div className="flex w-64 min-w-full flex-col gap-1">
                            {steps.map((step, index) => (
                                <div key={index} className="flex flex-wrap items-center gap-1">
                                    <Tooltip>
                                        <TooltipTrigger render={<Text size="xs" render={<span />} />}>
                                            <ActionStepSummary step={step} />
                                        </TooltipTrigger>
                                        <TooltipContent side="right" className="max-w-96">
                                            <ActionStepConditions step={step} />
                                        </TooltipContent>
                                    </Tooltip>
                                    <EventHealthWarning event={step.event} />
                                </div>
                            ))}
                        </div>
                    )
                },
            },
            {
                id: 'tags',
                header: 'Tags',
                enableSorting: false,
                cell: ({ row }) => <QuillTagsCell tags={row.original.tags ?? []} />,
            },
            {
                id: 'created_by',
                accessorKey: 'created_by',
                header: 'Created by',
                cell: ({ row }) => <AnalyticsOwner owner={row.original.created_by} className="max-w-40" />,
            },
            {
                id: 'created_at',
                accessorKey: 'created_at',
                header: 'Created',
                sortDescFirst: true,
                cell: ({ row }) => (
                    <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
                        <TZLabel time={row.original.created_at} />
                    </Text>
                ),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                enableResizing: false,
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <QuillActionRowMenu action={row.original} onDelete={() => deleteAction(row.original)} />
                ),
            },
        ]
    }, [currentProjectId, reloadAfterDelete, pinAction, unpinAction])

    const ordering = filters.ordering || DEFAULT_ORDERING
    const tableSorting: SortingState = [{ id: ordering.replace(/^-/, ''), desc: ordering.startsWith('-') }]
    const onSortingChange = ([sort]: SortingState): void =>
        setFilters({ ordering: sort ? `${sort.desc ? '-' : ''}${sort.id}` : DEFAULT_ORDERING })

    const clearSearchAndFilters = (): void => {
        setSearchTerm('')
        setFilters({ createdBy: [], tags: [] })
    }

    const renderBody = (): JSX.Element => {
        if (!hasLoadedActions) {
            return <QuillTableSkeleton label="Loading actions" />
        }
        if (actionsLoadFailed && !actionsResponseLoading) {
            return (
                <Empty data-attr="actions-table-error">
                    <EmptyHeader>
                        <EmptyTitle>Couldn't load actions</EmptyTitle>
                        <EmptyDescription>Check your connection and try again.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button variant="outline" onClick={loadActions}>
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (!actionsResponseLoading && actionCount < 1) {
            return <QuillActionsEmptyState filtered={hasActiveFilters} onClearFilters={clearSearchAndFilters} />
        }
        return (
            <Card size="sm" flush className="pt-0">
                <div
                    className={cn('transition-opacity', actionsResponseLoading && 'opacity-60')}
                    aria-busy={actionsResponseLoading}
                    data-attr="actions-table"
                >
                    <DataTable
                        columns={columns}
                        data={actionsList}
                        fullWidth
                        size="sm"
                        getRowId={(action) => String(action.id)}
                        sorting={tableSorting}
                        onSortingChange={onSortingChange}
                    />
                </div>
                {actionCount > ACTIONS_PER_PAGE && (
                    <QuillTablePagination
                        currentPage={page}
                        pageCount={Math.ceil(actionCount / ACTIONS_PER_PAGE)}
                        pageSize={ACTIONS_PER_PAGE}
                        total={actionCount}
                        onPageChange={setPage}
                    />
                )}
            </Card>
        )
    }

    return (
        <div className="flex flex-col gap-2" data-attr="manage-events-table">
            <div className="flex flex-wrap items-center gap-2">
                <AnalyticsSearchInput
                    value={searchTerm}
                    onChange={setSearchTerm}
                    label="Search for actions"
                    placeholder="Search for actions"
                    dataAttr="actions-search"
                    className="w-72 max-w-full"
                />
                <QuillActionsFilterMenu />
            </div>
            {renderBody()}
            <QuillDeleteReferencedActionDialog
                referenceCount={pendingDelete?.referenceCount ?? null}
                onCancel={() => setPendingDelete(null)}
                onConfirm={() => {
                    const performDelete = pendingDelete?.performDelete
                    setPendingDelete(null)
                    void performDelete?.()
                }}
            />
        </div>
    )
}
