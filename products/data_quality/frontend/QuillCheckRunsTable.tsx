import {
    Badge,
    Skeleton,
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
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { CHECK_STATUS_BADGE_VARIANTS } from './checkBadgeVariants'
import {
    UNPUBLISHED_REFRESH_EXPLANATION,
    byStatusAttention,
    checkRunDisplayName,
    runResultCell,
} from './checksConstants'
import { NARROW_ONLY, SKELETON_ROW_COUNT, WIDE_ONLY_CELL } from './checkTableLayout'
import type { DataQualityCheckRunApi } from './generated/api.schemas'

const EMPTY_VALUE = '-'

function RunStatus({ run }: { run: DataQualityCheckRunApi }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Badge variant={CHECK_STATUS_BADGE_VARIANTS[run.status] ?? 'default'}>{run.status}</Badge>
            {run.audited_staged_refresh ? (
                <Tooltip>
                    <TooltipTrigger render={<Badge />}>Unpublished refresh</TooltipTrigger>
                    <TooltipContent>{UNPUBLISHED_REFRESH_EXPLANATION}</TooltipContent>
                </Tooltip>
            ) : null}
        </div>
    )
}

function RunResult({ run }: { run: DataQualityCheckRunApi }): JSX.Element {
    const { label, tooltip } = runResultCell(run)
    if (!tooltip) {
        return <span>{label}</span>
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span />}>{label}</TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function RunError({ run }: { run: DataQualityCheckRunApi }): JSX.Element {
    if (!run.error) {
        return <span>{EMPTY_VALUE}</span>
    }
    return (
        <Tooltip>
            <TooltipTrigger
                render={<Text size="xs" variant="destructive" render={<span className="block max-w-xs truncate" />} />}
            >
                {run.error}
            </TooltipTrigger>
            <TooltipContent>{run.error}</TooltipContent>
        </Tooltip>
    )
}

function runDuration(run: DataQualityCheckRunApi): string {
    return run.duration_ms === null ? EMPTY_VALUE : humanFriendlyDuration(run.duration_ms / 1000, { maxUnits: 2 })
}

function RunRow({ run, showCheck }: { run: DataQualityCheckRunApi; showCheck: boolean }): JSX.Element {
    return (
        <TableRow>
            {showCheck && (
                <TableCell valign="top">
                    <span className="font-medium">{checkRunDisplayName(run)}</span>
                </TableCell>
            )}
            <TableCell valign="top">
                <div className="flex flex-col items-start gap-1">
                    <RunStatus run={run} />
                    <div className={cn(NARROW_ONLY, 'flex flex-col gap-1')}>
                        <RunResult run={run} />
                        {run.error && <RunError run={run} />}
                    </div>
                </div>
            </TableCell>
            <TableCell valign="top">{run.started_at ? <TZLabel time={run.started_at} /> : EMPTY_VALUE}</TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                {runDuration(run)}
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <RunResult run={run} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <RunError run={run} />
            </TableCell>
        </TableRow>
    )
}

export interface QuillCheckRunsTableProps {
    runs: DataQualityCheckRunApi[]
    loading?: boolean
    showCheck?: boolean
}

export function QuillCheckRunsTable({ runs, loading, showCheck = false }: QuillCheckRunsTableProps): JSX.Element {
    const sortedRuns = showCheck ? [...runs].sort(byStatusAttention) : runs

    return (
        <Table fullWidth size="sm" aria-busy={loading || undefined}>
            <TableHeader>
                <TableRow>
                    {showCheck && <TableHead>Check</TableHead>}
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Duration</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Result</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Error</TableHead>
                </TableRow>
            </TableHeader>
            {loading && sortedRuns.length === 0 ? (
                <TableBody>
                    {Array.from({ length: SKELETON_ROW_COUNT }, (_, index) => (
                        <TableRow key={index}>
                            <TableCell colSpan={6}>
                                <Skeleton className="h-5 w-full" />
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            ) : sortedRuns.length === 0 ? (
                <TableEmpty>
                    <Text size="xs" variant="muted">
                        No runs yet
                    </Text>
                </TableEmpty>
            ) : (
                <TableBody>
                    {sortedRuns.map((run) => (
                        <RunRow key={run.id} run={run} showCheck={showCheck} />
                    ))}
                </TableBody>
            )}
        </Table>
    )
}
