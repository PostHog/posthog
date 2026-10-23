import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

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
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    Pagination,
    PaginationButton,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
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

import type { DataModelingJobApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { MATERIALIZATION_JOBS_PAGE_SIZE, MaterializedViewOption, modelsUsageLogic } from './modelsUsageLogic'

const ALL_VIEWS: MaterializedViewOption = { id: 'all', name: 'All materialized views' }

const STATUS_VARIANTS: Record<string, 'success' | 'destructive' | 'warning' | 'default'> = {
    Completed: 'success',
    Failed: 'destructive',
    Running: 'warning',
    Cancelled: 'default',
    Skipped: 'default',
}

function engineLabel(engine: DataModelingJobApi['engine']): string {
    if (engine === 'managed_warehouse') {
        return 'Managed warehouse'
    }
    if (engine === 'clickhouse') {
        return 'ClickHouse'
    }
    if (engine === 'duckgres') {
        return 'Duckgres'
    }
    return engine
}

// Jobs can belong to models the saved-query list omits, such as endpoint materializations
// and soft-deleted models, so an unresolved ID is not necessarily a deleted model.
const UNAVAILABLE_MODEL = 'Unavailable model'

export function MaterializationJobsTable(): JSX.Element {
    const {
        materializationJobs,
        jobsLoading,
        jobsFailed,
        jobsPage,
        selectedSavedQueryId,
        materializedViewOptions,
        savedQueryNameById,
        managedWarehouseEnabled,
    } = useValues(modelsUsageLogic)
    const { refreshJobs, setJobsPage, setSelectedSavedQueryId, openModel } = useActions(modelsUsageLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const options = useMemo(() => [ALL_VIEWS, ...materializedViewOptions], [materializedViewOptions])
    const selected = options.find((option) => option.id === (selectedSavedQueryId ?? 'all')) ?? ALL_VIEWS
    const count = materializationJobs?.count ?? 0
    const jobs = materializationJobs?.results ?? []
    const pageCount = Math.max(Math.ceil(count / MATERIALIZATION_JOBS_PAGE_SIZE), 1)
    const pageIndex = jobsPage - 1
    const pageRange = getPaginationRange(pageCount, pageIndex)
    const firstRow = count === 0 ? 0 : pageIndex * MATERIALIZATION_JOBS_PAGE_SIZE + 1
    const lastRow = Math.min(firstRow + jobs.length - 1, count)

    return (
        <Card size="sm" className="min-w-0 gap-0">
            <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
                <div className="min-w-0">
                    <CardTitle role="heading" aria-level={3}>
                        Materialization jobs
                    </CardTitle>
                    <CardDescription>Every model refresh, newest first.</CardDescription>
                </div>
                <Combobox
                    items={options}
                    value={selected}
                    itemToStringValue={(option: MaterializedViewOption) => option.name}
                    isItemEqualToValue={(option, value) => option.id === value.id}
                    onValueChange={(option: MaterializedViewOption | null) =>
                        setSelectedSavedQueryId(!option || option.id === 'all' ? null : option.id)
                    }
                >
                    <ComboboxTrigger
                        ref={triggerRef}
                        render={<Button variant="outline" className="max-w-72 justify-between" />}
                        data-attr="models-usage-jobs-view-filter"
                    >
                        <span className="truncate">{selected.name}</span>
                    </ComboboxTrigger>
                    <ComboboxContent anchor={triggerRef} align="end" className="w-80 max-w-[calc(100vw-2rem)]">
                        <ComboboxInput placeholder="Search materialized views" showTrigger={false} />
                        <ComboboxEmpty>No materialized views found.</ComboboxEmpty>
                        <ComboboxList>
                            {(option: MaterializedViewOption) => (
                                <ComboboxItem key={option.id} value={option} title={option.name}>
                                    <span className="truncate">{option.name}</span>
                                </ComboboxItem>
                            )}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
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
                                    const modelName = job.saved_query_id
                                        ? (savedQueryNameById[job.saved_query_id] ?? UNAVAILABLE_MODEL)
                                        : 'Deleted model'
                                    return (
                                        <TableRow key={job.id}>
                                            <TableCell expand className="min-w-40 max-w-80">
                                                {job.saved_query_id && savedQueryNameById[job.saved_query_id] ? (
                                                    <LinkPrimitive
                                                        className="block truncate font-medium text-link-primary hover:underline"
                                                        to={urls.sqlEditor({ view_id: job.saved_query_id })}
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
                                                    {engineLabel(job.engine)}
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
                                No materialization jobs match this view.
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
