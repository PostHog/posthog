import { useActions, useValues } from 'kea'
import { Fragment, useState } from 'react'

import { IconClock, IconRefresh, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
    Heading,
    Progress,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
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
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import {
    DEFAULT_JOBS_PAGE_SIZE,
    materializationJobsLogic,
} from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import {
    MATERIALIZATION_LOG_LEVELS,
    computeJobDuration,
    getMaterializationStatusMessage,
    jobLogsWindow,
} from 'scenes/data-warehouse/saved_queries/materializationJobUtils'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { QuillCheckCallout } from 'products/data_quality/frontend/QuillCheckCallout'
import { QuillRowExpandButton } from 'products/data_quality/frontend/QuillRowExpandButton'
import {
    DataModelingJobsListEngine,
    type DataModelingJobApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'
import { MaterializationRunError } from 'products/data_warehouse/frontend/shared/components/MaterializationRunError'

import { MATERIALIZATION_ENGINE_LABELS } from '../modelsUsageLogic'
import { DATA_WAREHOUSE_ICON_COLOR, RUN_STATUS_BADGE_VARIANTS, runStatusLabel } from './quillNodeDetailBadges'

const WIDE_ONLY_CELL = 'hidden @min-[48rem]/main-content:table-cell'
const COLUMN_COUNT = 7
const RUN_HISTORY_ENGINES = [DataModelingJobsListEngine.Clickhouse, DataModelingJobsListEngine.ManagedWarehouse]

function JobStatus({ job }: { job: DataModelingJobApi }): JSX.Element {
    const { status, rows_materialized, rows_expected } = job
    const progressPercentage =
        rows_expected && rows_expected > 0 ? Math.min(100, (rows_materialized / rows_expected) * 100) : 0

    if (status === 'Running' && progressPercentage > 0 && rows_expected !== null) {
        return (
            <Tooltip>
                <TooltipTrigger render={<div tabIndex={0} className="w-16" />}>
                    <Progress value={progressPercentage} aria-label="Run progress" />
                </TooltipTrigger>
                <TooltipContent side="right">
                    {getMaterializationStatusMessage(rows_materialized, progressPercentage, rows_expected)}
                </TooltipContent>
            </Tooltip>
        )
    }
    const badge = <Badge variant={RUN_STATUS_BADGE_VARIANTS[status] ?? 'warning'}>{runStatusLabel(status)}</Badge>
    if (!job.error) {
        return badge
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span tabIndex={0} aria-label={`${status}. ${job.error}`} />}>
                {badge}
            </TooltipTrigger>
            <TooltipContent>
                <span className="font-mono whitespace-pre-wrap">{job.error}</span>
            </TooltipContent>
        </Tooltip>
    )
}

function RefreshMode({ job }: { job: DataModelingJobApi }): JSX.Element {
    if (job.run_mode === 'incremental') {
        return <span>Incremental</span>
    }
    if (job.run_mode !== 'full_refresh') {
        return <span>-</span>
    }
    if (!job.full_refresh_reason) {
        return <span>Full refresh</span>
    }
    const explanation = `Full refresh. Reason: ${job.full_refresh_reason}.`
    return (
        <Tooltip>
            <TooltipTrigger
                render={<span tabIndex={0} aria-label={explanation} className="cursor-help border-b border-dotted" />}
            >
                Full refresh
            </TooltipTrigger>
            <TooltipContent>{explanation}</TooltipContent>
        </Tooltip>
    )
}

function RowsWritten({ job }: { job: DataModelingJobApi }): JSX.Element {
    const { rows_materialized, status, run_mode } = job
    if ((status === 'Running' || status === 'Cancelled' || status === 'Skipped') && rows_materialized === 0) {
        return <span>~</span>
    }
    const count = humanFriendlyNumber(rows_materialized)
    if (!run_mode) {
        return <span>{count}</span>
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span tabIndex={0} />}>{count}</TooltipTrigger>
            <TooltipContent>
                {run_mode === 'incremental'
                    ? 'Rows this run synced, including the re-read lookback window.'
                    : 'This run rebuilt the whole table. This is its full row count.'}
            </TooltipContent>
        </Tooltip>
    )
}

function JobLogs({ job, viewId }: { job: DataModelingJobApi; viewId: string }): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const showDebugLogs = user?.is_staff || user?.is_impersonated

    return (
        <div className="flex min-w-0 flex-col gap-2 p-2">
            <MaterializationRunError error={job.error} status={job.status} />
            <LogsViewer
                logicKey={`data_modeling_run:${job.id}`}
                sourceType="data_modeling_run"
                sourceId={viewId}
                groupByInstanceId={false}
                hideDateFilter
                hideLevelsFilter
                hideInstanceIdColumn
                defaultFilters={{
                    instanceId: job.workflow_run_id ?? undefined,
                    ...jobLogsWindow(job, timezone),
                    levels: showDebugLogs ? ['DEBUG', ...MATERIALIZATION_LOG_LEVELS] : MATERIALIZATION_LOG_LEVELS,
                }}
            />
        </div>
    )
}

function RunHistoryEmpty({
    failed,
    materialized,
    kind,
}: {
    failed: boolean
    materialized: boolean
    kind: 'view' | 'endpoint'
}): JSX.Element {
    const [title, description] = failed
        ? ["Couldn't load runs", 'Use Refresh runs to try again.']
        : materialized
          ? ['No runs yet', 'Runs show up here after the first refresh. Use Sync now to start one.']
          : ['No runs yet', `Materialize this ${kind} to store its results and refresh them on a schedule.`]
    return (
        <Empty>
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color={DATA_WAREHOUSE_ICON_COLOR}>
                        {failed ? <IconWarning /> : <IconClock />}
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>{title}</EmptyTitle>
                <EmptyDescription>{description}</EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}

export function QuillMaterializationRunHistory({
    viewId,
    kind,
    materialized,
    showRefreshMode,
}: {
    viewId: string
    kind: 'view' | 'endpoint'
    materialized: boolean
    showRefreshMode: boolean
}): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId, kind })
    const {
        jobsPage,
        jobsPageResults,
        runHistoryLoading,
        runHistoryError,
        selectedRunHistoryEngine,
        startingMaterialization,
    } = useValues(jobsLogic)
    const { loadDataModelingJobs, loadRunHistoryJobs, setJobsPage, loadOlderJobsPage, setSelectedRunHistoryEngine } =
        useActions(jobsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const managedWarehouseEnabled = !!featureFlags[FEATURE_FLAGS.MANAGED_TRINO_QUERY]
    const [expandedJobIds, setExpandedJobIds] = useState<string[]>([])

    const jobs = jobsPage > 1 && runHistoryError ? [] : (jobsPageResults?.results ?? [])
    const count = jobsPageResults?.count ?? 0
    const firstRow = count === 0 ? 0 : (jobsPage - 1) * DEFAULT_JOBS_PAGE_SIZE + 1
    const lastRow = Math.min(firstRow + jobs.length - 1, count)
    const showLoader = runHistoryLoading && (jobsPage > 1 || !jobsPageResults?.results?.length)
    const refreshRuns = (): void =>
        jobsPage > 1
            ? loadOlderJobsPage()
            : selectedRunHistoryEngine === DataModelingJobsListEngine.Clickhouse
              ? loadDataModelingJobs()
              : loadRunHistoryJobs()
    const toggleJob = (jobId: string): void =>
        setExpandedJobIds(
            expandedJobIds.includes(jobId) ? expandedJobIds.filter((id) => id !== jobId) : [...expandedJobIds, jobId]
        )

    return (
        <section className="flex flex-col gap-2 border-t border-border pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading size="base" render={<h3 className="m-0" />}>
                    Run history
                </Heading>
                <div className="flex items-center gap-2">
                    {managedWarehouseEnabled && (
                        <Select
                            value={selectedRunHistoryEngine}
                            onValueChange={(engine) => engine && setSelectedRunHistoryEngine(engine)}
                        >
                            <SelectTrigger data-attr="materialization-run-history-engine-filter">
                                <SelectValue>
                                    {(engine: DataModelingJobsListEngine) => MATERIALIZATION_ENGINE_LABELS[engine]}
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent align="end" alignItemWithTrigger={false}>
                                {RUN_HISTORY_ENGINES.map((engine) => (
                                    <SelectItem key={engine} value={engine}>
                                        {MATERIALIZATION_ENGINE_LABELS[engine]}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    )}
                    <Button
                        variant="outline"
                        size="icon"
                        onClick={refreshRuns}
                        loading={runHistoryLoading}
                        disabledReason={startingMaterialization ? 'Materialization is starting' : undefined}
                        tooltip="Refresh runs"
                        aria-label="Refresh runs"
                    >
                        <IconRefresh />
                    </Button>
                </div>
            </div>
            {runHistoryError && jobs.length > 0 && (
                <QuillCheckCallout tone="destructive">
                    Couldn't load runs. Use Refresh runs to try again.
                </QuillCheckCallout>
            )}
            <Table fullWidth size="sm" aria-busy={showLoader || undefined}>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-0" />
                        <TableHead>Status</TableHead>
                        {showRefreshMode && <TableHead className={WIDE_ONLY_CELL}>Refresh mode</TableHead>}
                        <TableHead expand className={WIDE_ONLY_CELL}>
                            Error
                        </TableHead>
                        <TableHead align="right">Rows</TableHead>
                        <TableHead>Updated</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Duration</TableHead>
                    </TableRow>
                </TableHeader>
                {showLoader ? (
                    <TableBody>
                        {Array.from({ length: 3 }, (_, index) => (
                            <TableRow key={index}>
                                <TableCell colSpan={COLUMN_COUNT}>
                                    <Skeleton className="h-5 w-full" />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                ) : jobs.length === 0 ? (
                    <TableEmpty>
                        <RunHistoryEmpty failed={runHistoryError} materialized={materialized} kind={kind} />
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {jobs.map((job) => {
                            const expanded = expandedJobIds.includes(job.id)
                            return (
                                <Fragment key={job.id}>
                                    <TableRow>
                                        <TableCell>
                                            <QuillRowExpandButton
                                                expanded={expanded}
                                                label={expanded ? 'Hide run logs' : 'Show run logs'}
                                                onToggle={() => toggleJob(job.id)}
                                                dataAttr="materialization-run-expand"
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <JobStatus job={job} />
                                        </TableCell>
                                        {showRefreshMode && (
                                            <TableCell className={WIDE_ONLY_CELL}>
                                                <RefreshMode job={job} />
                                            </TableCell>
                                        )}
                                        <TableCell expand className={WIDE_ONLY_CELL}>
                                            <Text
                                                size="xs"
                                                variant={job.status === 'Failed' ? 'destructive' : 'muted'}
                                                render={<span className="block max-w-60 truncate" />}
                                            >
                                                {job.error?.split('\n')[0]}
                                            </Text>
                                        </TableCell>
                                        <TableCell align="right" className="tabular-nums">
                                            <RowsWritten job={job} />
                                        </TableCell>
                                        <TableCell className="whitespace-nowrap">
                                            {job.last_run_at ? <TZLabel time={job.last_run_at} /> : '-'}
                                        </TableCell>
                                        <TableCell className={`${WIDE_ONLY_CELL} whitespace-nowrap tabular-nums`}>
                                            {computeJobDuration(job)}
                                        </TableCell>
                                    </TableRow>
                                    {expanded && (
                                        <TableRow>
                                            <TableCell colSpan={COLUMN_COUNT} className="max-w-0">
                                                <JobLogs job={job} viewId={viewId} />
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </Fragment>
                            )
                        })}
                    </TableBody>
                )}
            </Table>
            {(count > 0 || jobsPage > 1) && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Text size="xs" variant="muted" render={<span className="tabular-nums" />}>
                        {count > 0 ? `${firstRow}-${lastRow} of ${count} runs` : ''}
                    </Text>
                    <div className="flex items-center gap-2">
                        <Button
                            variant="outline"
                            disabledReason={jobsPage > 1 ? undefined : 'This is the newest page'}
                            onClick={() => setJobsPage(jobsPage - 1)}
                        >
                            Newer
                        </Button>
                        <Button
                            variant="outline"
                            disabledReason={jobsPageResults?.next ? undefined : 'No older runs'}
                            onClick={() => setJobsPage(jobsPage + 1)}
                        >
                            Older
                        </Button>
                    </div>
                </div>
            )}
        </section>
    )
}
