import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Pagination,
    PaginationButton,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    getPaginationRange,
} from 'lib/ui/quill'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { computeJobDuration } from 'scenes/data-warehouse/saved_queries/materializationJobUtils'
import { urls } from 'scenes/urls'

import { DataModelingJobsListStatus } from 'products/data_warehouse/frontend/generated/api.schemas'

import { MATERIALIZATION_ENGINE_LABELS, MATERIALIZATION_JOBS_PAGE_SIZE, modelsUsageLogic } from './modelsUsageLogic'

const STATUS_VARIANTS: Record<string, 'success' | 'destructive' | 'warning' | 'default'> = {
    Completed: 'success',
    Failed: 'destructive',
    Running: 'warning',
    Cancelled: 'default',
    Skipped: 'default',
}

export function MaterializationJobsTable({
    savedQueryIdToNodeId,
}: {
    savedQueryIdToNodeId: Record<string, string>
}): JSX.Element {
    const { materializationJobs, jobsLoading, jobsFailed, jobsPage, managedWarehouseEnabled, selectedJobStatus } =
        useValues(modelsUsageLogic)
    const { refreshJobs, setJobsPage, setSelectedJobStatus, openModel } = useActions(modelsUsageLogic)
    const count = materializationJobs?.count ?? 0
    const jobs = materializationJobs?.results ?? []
    const pageCount = Math.max(Math.ceil(count / MATERIALIZATION_JOBS_PAGE_SIZE), 1)
    const pageIndex = jobsPage - 1
    const pageRange = getPaginationRange(pageCount, pageIndex)
    const firstRow = count === 0 ? 0 : pageIndex * MATERIALIZATION_JOBS_PAGE_SIZE + 1
    const lastRow = Math.min(firstRow + jobs.length - 1, count)

    return (
        <Card size="sm" className="min-w-0 gap-0">
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
                <div className="min-w-0">
                    <CardTitle role="heading" aria-level={3}>
                        Materialization jobs
                    </CardTitle>
                    <CardDescription>Model refreshes since the selected start date, newest first.</CardDescription>
                </div>
                <Select
                    value={selectedJobStatus ?? 'all'}
                    onValueChange={(value) =>
                        value && setSelectedJobStatus(value === 'all' ? null : (value as DataModelingJobsListStatus))
                    }
                >
                    <SelectTrigger data-attr="models-usage-job-status-filter" disabled={jobsLoading}>
                        <SelectValue>
                            {(value: string) =>
                                value === 'all' ? 'All statuses' : value === 'Cancelled' ? 'Canceled' : value
                            }
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent align="end" alignItemWithTrigger={false}>
                        <SelectItem value="all">All statuses</SelectItem>
                        <SelectItem value={DataModelingJobsListStatus.Completed}>Completed</SelectItem>
                        <SelectItem value={DataModelingJobsListStatus.Running}>Running</SelectItem>
                        <SelectItem value={DataModelingJobsListStatus.Failed}>Failed</SelectItem>
                        <SelectItem value={DataModelingJobsListStatus.Cancelled}>Canceled</SelectItem>
                        <SelectItem value={DataModelingJobsListStatus.Skipped}>Skipped</SelectItem>
                    </SelectContent>
                </Select>
            </CardHeader>
            {jobsFailed ? (
                <CardContent className="flex items-center justify-between gap-3 py-6">
                    <Text variant="muted">Could not load materialization jobs.</Text>
                    <Button variant="outline" onClick={refreshJobs} loading={jobsLoading}>
                        Try again
                    </Button>
                </CardContent>
            ) : (
                <CardContent className="relative overflow-x-auto p-0">
                    <Table fullWidth aria-busy={jobsLoading}>
                        <TableHeader>
                            <TableRow>
                                <TableHead expand>Model</TableHead>
                                <TableHead>Status</TableHead>
                                {managedWarehouseEnabled ? <TableHead>Engine</TableHead> : null}
                                <TableHead className="hidden @min-[48rem]/main-content:table-cell">Started</TableHead>
                                <TableHead className="hidden @min-[48rem]/main-content:table-cell">Duration</TableHead>
                                <TableHead align="right" className="hidden @min-[48rem]/main-content:table-cell">
                                    Rows written
                                </TableHead>
                                <TableHead align="right" className="hidden @min-[48rem]/main-content:table-cell">
                                    Bytes read
                                </TableHead>
                            </TableRow>
                        </TableHeader>
                        {jobs.length > 0 ? (
                            <TableBody>
                                {jobs.map((job) => {
                                    const modelName = job.saved_query_name ?? 'Deleted model'
                                    const nodeId = job.saved_query_id
                                        ? savedQueryIdToNodeId[job.saved_query_id]
                                        : undefined
                                    return (
                                        <TableRow key={job.id}>
                                            <TableCell expand className="min-w-40 max-w-80">
                                                {nodeId && !job.saved_query_deleted ? (
                                                    <LinkPrimitive
                                                        className="block truncate font-medium text-link-primary hover:underline"
                                                        to={urls.nodeDetail(nodeId)}
                                                        onClick={openModel}
                                                        title={modelName}
                                                    >
                                                        {modelName}
                                                    </LinkPrimitive>
                                                ) : (
                                                    <Text
                                                        variant="muted"
                                                        render={<span />}
                                                        className="block truncate"
                                                        title={modelName}
                                                    >
                                                        {modelName}
                                                        {job.saved_query_deleted ? ' (deleted)' : ''}
                                                    </Text>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={STATUS_VARIANTS[job.status] ?? 'default'}>
                                                    {job.status === 'Cancelled' ? 'Canceled' : job.status}
                                                </Badge>
                                            </TableCell>
                                            {managedWarehouseEnabled ? (
                                                <TableCell className="whitespace-nowrap">
                                                    {MATERIALIZATION_ENGINE_LABELS[job.engine] ?? job.engine}
                                                </TableCell>
                                            ) : null}
                                            <TableCell className="hidden whitespace-nowrap @min-[48rem]/main-content:table-cell">
                                                <TZLabel time={job.created_at} />
                                            </TableCell>
                                            <TableCell className="hidden whitespace-nowrap tabular-nums @min-[48rem]/main-content:table-cell">
                                                {computeJobDuration(job)}
                                            </TableCell>
                                            <TableCell
                                                align="right"
                                                className="hidden whitespace-nowrap tabular-nums @min-[48rem]/main-content:table-cell"
                                            >
                                                {humanFriendlyNumber(job.rows_materialized)}
                                            </TableCell>
                                            <TableCell
                                                align="right"
                                                className="hidden whitespace-nowrap tabular-nums @min-[48rem]/main-content:table-cell"
                                            >
                                                {job.read_bytes === null
                                                    ? 'Not measured'
                                                    : humanizeBytes(job.read_bytes)}
                                            </TableCell>
                                        </TableRow>
                                    )
                                })}
                            </TableBody>
                        ) : jobsLoading && !materializationJobs ? (
                            <TableBody>
                                <TableRow>
                                    <TableCell colSpan={managedWarehouseEnabled ? 7 : 6}>
                                        <div className="flex justify-center py-8">
                                            <Spinner />
                                        </div>
                                    </TableCell>
                                </TableRow>
                            </TableBody>
                        ) : (
                            <TableEmpty className="py-8 text-secondary">
                                No materialization jobs match these filters.
                            </TableEmpty>
                        )}
                    </Table>
                    {jobsLoading && materializationJobs ? (
                        <div className="absolute inset-0 flex items-center justify-center bg-background/60">
                            <Spinner />
                        </div>
                    ) : null}
                </CardContent>
            )}
            {!jobsFailed && count > 0 ? (
                <CardFooter className="flex flex-row flex-wrap items-center justify-between gap-2 border-t border-border">
                    <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                        {firstRow}-{lastRow} of {pluralize(count, 'job')}
                    </Text>
                    {pageCount > 1 ? (
                        <Pagination className="w-auto">
                            <PaginationContent>
                                <PaginationItem>
                                    <PaginationPrevious
                                        disabled={jobsLoading || pageIndex === 0}
                                        onClick={() => setJobsPage(jobsPage - 1)}
                                    />
                                </PaginationItem>
                                {pageRange.map((item, index) =>
                                    item === 'ellipsis' ? (
                                        <PaginationItem key={`ellipsis-${index}`}>
                                            <PaginationEllipsis />
                                        </PaginationItem>
                                    ) : (
                                        <PaginationItem key={item}>
                                            <PaginationButton
                                                isActive={item === pageIndex}
                                                disabled={jobsLoading}
                                                onClick={() => setJobsPage(item + 1)}
                                            >
                                                {item + 1}
                                            </PaginationButton>
                                        </PaginationItem>
                                    )
                                )}
                                <PaginationItem>
                                    <PaginationNext
                                        disabled={jobsLoading || pageIndex === pageCount - 1}
                                        onClick={() => setJobsPage(jobsPage + 1)}
                                    />
                                </PaginationItem>
                            </PaginationContent>
                        </Pagination>
                    ) : null}
                </CardFooter>
            ) : null}
        </Card>
    )
}
