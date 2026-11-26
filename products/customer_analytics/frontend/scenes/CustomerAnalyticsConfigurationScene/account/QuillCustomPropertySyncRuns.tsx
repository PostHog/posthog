import posthog from 'posthog-js'
import { Fragment, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconExternal, IconInfo, IconRefresh } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Pagination,
    PaginationContent,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
    Skeleton,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { CustomPropertySyncRunApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    ACCOUNT_SEGMENT_LABELS,
    RUN_STATUS_LABELS,
    runDuration,
    TARGET_LABELS,
    updatedShare,
} from './customPropertySyncRunFormat'
import { CustomPropertySyncRunLogs } from './CustomPropertySyncRunLogs'
import { type CustomPropertySyncRunsProps } from './CustomPropertySyncRuns'
import { runOutcomeNote } from './customPropertyTypes'

const PAGE_SIZE = 20

const BADGE_VARIANT_BY_RUN_STATUS: Record<string, 'success' | 'info' | 'destructive'> = {
    completed: 'success',
    running: 'info',
    failed: 'destructive',
}

const RUN_TRIGGER_LABELS: Record<string, string> = {
    scheduled: 'Scheduled',
    sync: 'Sync now',
    manual: 'Backfill',
    backfill: 'Auto backfill',
}

function HeadWithHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {label}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </span>
    )
}

function RunCount({ value }: { value: number }): JSX.Element {
    return <span className={cn(value ? 'font-medium' : 'text-muted-foreground')}>{humanFriendlyNumber(value)}</span>
}

function EmptyValue(): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span className="m-0" />}>
            -
        </Text>
    )
}

export function QuillCustomPropertySyncRuns({
    runs,
    loading,
    loadFailed,
    targetType,
    logSourceId,
    syncsUrl,
    searchTerm,
    entryCount,
    currentPage,
    onSearch,
    onForward,
    onBackward,
    onReload,
}: CustomPropertySyncRunsProps): JSX.Element {
    const [expandedRunIds, setExpandedRunIds] = useState<string[]>([])

    const labels = TARGET_LABELS[targetType]
    const accountRuns = targetType === 'account'
    const runLogsAvailable = !accountRuns && !!logSourceId
    const pageCount = Math.ceil(entryCount / PAGE_SIZE)
    const columnCount = (runLogsAvailable ? 1 : 0) + 7 + (syncsUrl ? 1 : 0)

    const toggleRunLogs = (run: CustomPropertySyncRunApi): void => {
        if (expandedRunIds.includes(run.id)) {
            setExpandedRunIds(expandedRunIds.filter((id) => id !== run.id))
            return
        }

        setExpandedRunIds([...expandedRunIds, run.id])
        // Pinned: analytics event name, renaming breaks dashboards.
        posthog.capture('warehouse property run logs viewed', {
            target_type: targetType,
            run_status: run.status,
        })
    }

    if (loadFailed) {
        return (
            <Item tone="destructive" size="sm" className="flex-wrap">
                <ItemContent>
                    <ItemDescription>Couldn't load run history.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={onReload}>
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    return (
        <div className="flex w-full flex-col gap-2">
            <div className="flex items-center gap-2">
                <Button
                    variant="outline"
                    size="icon"
                    aria-label="Refresh runs"
                    tooltip="Refresh runs"
                    onClick={onReload}
                    loading={loading}
                    // Pinned because autocapture dashboards and browser tests use this interaction name.
                    data-attr="custom-property-sync-runs-refresh"
                >
                    <IconRefresh />
                </Button>
                <Input
                    type="search"
                    size="sm"
                    placeholder="Search runs"
                    aria-label="Search runs"
                    value={searchTerm}
                    onChange={(event) => onSearch(event.target.value)}
                    className="w-full max-w-sm"
                />
            </div>
            {loading && runs.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <Table fullWidth className="rounded-md border border-border">
                    <TableHeader>
                        <TableRow>
                            {runLogsAvailable && <TableHead />}
                            <TableHead>
                                <HeadWithHelp
                                    label="Status"
                                    help={
                                        accountRuns
                                            ? 'Whether this account segment finished. A completed run can update zero accounts when no mapped values changed.'
                                            : 'Whether the run finished. A completed run can update nobody when no mapped values changed.'
                                    }
                                />
                            </TableHead>
                            <TableHead>
                                {accountRuns ? (
                                    <HeadWithHelp
                                        label="Segment"
                                        help="Tracked and ignored accounts run separately. Ignored accounts stay in sync because a property change can make them tracked later."
                                    />
                                ) : (
                                    <HeadWithHelp
                                        label="Trigger"
                                        help="What started the run: the table schedule, Sync now, or Backfill."
                                    />
                                )}
                            </TableHead>
                            <TableHead align="right">
                                <HeadWithHelp
                                    label="Rows read"
                                    help={
                                        accountRuns
                                            ? 'Rows read from the materialized view snapshot for this account segment.'
                                            : 'Warehouse rows this sync staged.'
                                    }
                                />
                            </TableHead>
                            <TableHead align="right" expand>
                                <HeadWithHelp
                                    label="Updated"
                                    help={
                                        accountRuns
                                            ? `How many ${labels.entityPlural} this run updated, out of the rows whose mapped values changed.`
                                            : `How many ${labels.entityPlural} this run updated, out of the rows whose mapped values changed. A run that stopped part way shows how far it got.`
                                    }
                                />
                            </TableHead>
                            <TableHead>
                                {accountRuns ? (
                                    <HeadWithHelp
                                        label="Run"
                                        help="The materialization job for this update. Share this identifier when asking support for help."
                                    />
                                ) : null}
                            </TableHead>
                            <TableHead>Duration</TableHead>
                            <TableHead>Finished</TableHead>
                            {syncsUrl && <TableHead />}
                        </TableRow>
                    </TableHeader>
                    {runs.length === 0 ? (
                        <TableEmpty>
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>
                                        {searchTerm
                                            ? 'No runs match your search.'
                                            : accountRuns
                                              ? 'No runs yet. Run the source view to start a sync.'
                                              : 'No runs yet. Sync or backfill the source to start a run.'}
                                    </EmptyTitle>
                                </EmptyHeader>
                            </Empty>
                        </TableEmpty>
                    ) : (
                        <TableBody>
                            {runs.map((run) => {
                                const note = runOutcomeNote(run, labels.entityPlural)
                                const share = updatedShare(run.existing, run.changed)
                                // A run recorded before its job id was stored has no log lines to find.
                                const runLogsExpandable = runLogsAvailable && !!run.workflow_run_id
                                const isExpanded = expandedRunIds.includes(run.id)

                                return (
                                    <Fragment key={run.id}>
                                        <TableRow>
                                            {runLogsAvailable && (
                                                <TableCell>
                                                    {runLogsExpandable && (
                                                        <Button
                                                            size="icon-sm"
                                                            aria-label={isExpanded ? 'Hide run logs' : 'Show run logs'}
                                                            aria-expanded={isExpanded}
                                                            onClick={() => toggleRunLogs(run)}
                                                        >
                                                            {isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                                        </Button>
                                                    )}
                                                </TableCell>
                                            )}
                                            <TableCell>
                                                <div className="flex items-center gap-2">
                                                    {run.error ? (
                                                        <Tooltip>
                                                            <TooltipTrigger
                                                                render={
                                                                    <Badge
                                                                        variant={
                                                                            BADGE_VARIANT_BY_RUN_STATUS[run.status] ??
                                                                            'default'
                                                                        }
                                                                    />
                                                                }
                                                            >
                                                                {RUN_STATUS_LABELS[run.status] ?? run.status}
                                                            </TooltipTrigger>
                                                            <TooltipContent className="max-w-80">
                                                                {run.error}
                                                            </TooltipContent>
                                                        </Tooltip>
                                                    ) : (
                                                        <Badge
                                                            variant={
                                                                BADGE_VARIANT_BY_RUN_STATUS[run.status] ?? 'default'
                                                            }
                                                        >
                                                            {run.status === 'running' && <Spinner />}
                                                            {RUN_STATUS_LABELS[run.status] ?? run.status}
                                                        </Badge>
                                                    )}
                                                    {note && (
                                                        <Tooltip>
                                                            <TooltipTrigger
                                                                render={
                                                                    <Text
                                                                        size="xs"
                                                                        variant="muted"
                                                                        render={
                                                                            <span className="m-0 whitespace-nowrap" />
                                                                        }
                                                                    />
                                                                }
                                                            >
                                                                {note.label}
                                                            </TooltipTrigger>
                                                            <TooltipContent className="max-w-80">
                                                                {note.tooltip}
                                                            </TooltipContent>
                                                        </Tooltip>
                                                    )}
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                {accountRuns ? (
                                                    run.account_segment ? (
                                                        <Badge>
                                                            {ACCOUNT_SEGMENT_LABELS[run.account_segment] ??
                                                                run.account_segment}
                                                        </Badge>
                                                    ) : (
                                                        <EmptyValue />
                                                    )
                                                ) : (
                                                    <Badge>{RUN_TRIGGER_LABELS[run.trigger] ?? run.trigger}</Badge>
                                                )}
                                            </TableCell>
                                            <TableCell align="right">
                                                <RunCount value={run.rows_read} />
                                            </TableCell>
                                            <TableCell align="right">
                                                <span className="whitespace-nowrap">
                                                    <RunCount value={run.existing} />
                                                    <span className="text-muted-foreground">
                                                        {' '}
                                                        of {humanFriendlyNumber(run.changed)} changed
                                                        {share ? ` (${share})` : ''}
                                                    </span>
                                                </span>
                                            </TableCell>
                                            <TableCell>
                                                {accountRuns ? (
                                                    run.workflow_run_id ? (
                                                        <Tooltip>
                                                            <TooltipTrigger
                                                                render={
                                                                    run.temporal_url ? (
                                                                        <Button
                                                                            variant="link-foreground"
                                                                            size="sm"
                                                                            nativeButton={false}
                                                                            render={
                                                                                <LinkPrimitive
                                                                                    to={run.temporal_url}
                                                                                    target="_blank"
                                                                                />
                                                                            }
                                                                        />
                                                                    ) : (
                                                                        <span />
                                                                    )
                                                                }
                                                            >
                                                                <code>{run.workflow_run_id.slice(0, 8)}</code>
                                                            </TooltipTrigger>
                                                            <TooltipContent>
                                                                <div className="flex flex-col gap-1">
                                                                    <span>Temporal run: {run.workflow_run_id}</span>
                                                                    {run.workflow_id && (
                                                                        <span>Workflow: {run.workflow_id}</span>
                                                                    )}
                                                                    {run.job_id && <span>Job: {run.job_id}</span>}
                                                                    {(run.attempt ?? 0) > 1 && (
                                                                        <span>Attempt: {run.attempt}</span>
                                                                    )}
                                                                </div>
                                                            </TooltipContent>
                                                        </Tooltip>
                                                    ) : (
                                                        <EmptyValue />
                                                    )
                                                ) : null}
                                            </TableCell>
                                            <TableCell>{runDuration(run)}</TableCell>
                                            <TableCell>
                                                {run.finished_at ? <TZLabel time={run.finished_at} /> : <EmptyValue />}
                                            </TableCell>
                                            {syncsUrl && (
                                                <TableCell>
                                                    <Button
                                                        size="icon-sm"
                                                        aria-label="Open the source's warehouse history"
                                                        tooltip="Open the source's warehouse history"
                                                        nativeButton={false}
                                                        render={<LinkPrimitive to={syncsUrl} target="_blank" />}
                                                    >
                                                        <IconExternal />
                                                    </Button>
                                                </TableCell>
                                            )}
                                        </TableRow>
                                        {isExpanded && runLogsExpandable && logSourceId && (
                                            <TableRow>
                                                <TableCell colSpan={columnCount}>
                                                    <CustomPropertySyncRunLogs run={run} logSourceId={logSourceId} />
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </Fragment>
                                )
                            })}
                        </TableBody>
                    )}
                </Table>
            )}
            {pageCount > 1 && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Text size="xs" variant="muted" render={<span className="m-0 tabular-nums" translate="no" />}>
                        {(currentPage - 1) * PAGE_SIZE + 1}-{Math.min(currentPage * PAGE_SIZE, entryCount)} of{' '}
                        {entryCount}
                    </Text>
                    <Pagination className="w-auto">
                        <PaginationContent>
                            <PaginationItem>
                                <PaginationPrevious disabled={currentPage <= 1} onClick={onBackward}>
                                    <span className="sr-only">Previous</span>
                                </PaginationPrevious>
                            </PaginationItem>
                            <PaginationItem>
                                <PaginationNext disabled={currentPage >= pageCount} onClick={onForward}>
                                    <span className="sr-only">Next</span>
                                </PaginationNext>
                            </PaginationItem>
                        </PaginationContent>
                    </Pagination>
                </div>
            )}
        </div>
    )
}
