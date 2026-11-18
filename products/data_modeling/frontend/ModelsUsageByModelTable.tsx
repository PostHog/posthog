import { useActions, useValues } from 'kea'

import { IconSort } from '@posthog/icons'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import {
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
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    getPaginationRange,
} from 'lib/ui/quill'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { DataModelingUsageListEngine, type ModelUsageRowApi } from './generated/api.schemas'
import { modelsUsageLogic, type ModelsUsageSortBy } from './modelsUsageLogic'
import { UsageNotAvailable } from './UsageNotAvailable'

const PAGE_SIZE = 20

function engineBytes(row: ModelUsageRowApi, engine: string): number | null {
    return row.engines.find((item) => item.engine === engine)?.read_bytes ?? null
}

export function ModelsUsageByModelTable({
    savedQueryIdToNodeId,
}: {
    savedQueryIdToNodeId: Record<string, string>
}): JSX.Element | null {
    const { usage, usageLoading, page, managedWarehouseEnabled, selectedEngine, sortBy, sortDirection } =
        useValues(modelsUsageLogic)
    const { setPage, openModel, sortModels } = useActions(modelsUsageLogic)

    if (!usage || usage.overview.runs === 0) {
        return null
    }

    const pageCount = Math.max(Math.ceil(usage.count / PAGE_SIZE), 1)
    const pageIndex = page - 1
    const pageRange = getPaginationRange(pageCount, pageIndex)
    const firstRow = usage.count === 0 ? 0 : pageIndex * PAGE_SIZE + 1
    const lastRow = Math.min(firstRow + usage.models.length - 1, usage.count)
    const showEngineColumns = managedWarehouseEnabled && selectedEngine === DataModelingUsageListEngine.All

    const columns: { key: ModelsUsageSortBy; label: string; className?: string }[] = [
        { key: 'name', label: 'Model' },
        ...(showEngineColumns
            ? [
                  { key: 'clickhouse_read_bytes' as ModelsUsageSortBy, label: 'ClickHouse bytes' },
                  { key: 'managed_warehouse_read_bytes' as ModelsUsageSortBy, label: 'Managed warehouse bytes' },
              ]
            : [{ key: 'read_bytes' as ModelsUsageSortBy, label: 'Bytes read' }]),
        { key: 'cpu_microseconds', label: 'CPU time', className: 'hidden @min-[48rem]/main-content:table-cell' },
        { key: 'runs', label: 'Runs' },
    ]

    return (
        <Card size="sm" className="min-w-0 gap-0">
            <CardHeader className="border-b border-border pb-3">
                <CardTitle role="heading" aria-level={3}>
                    Usage by model
                </CardTitle>
                <CardDescription>
                    Review refresh schedules and query filters for models with high usage.
                </CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
                <Table fullWidth aria-busy={usageLoading}>
                    <TableHeader>
                        <TableRow>
                            {columns.map((column) => (
                                <TableHead
                                    key={column.key}
                                    expand={column.key === 'name'}
                                    align={column.key === 'name' ? 'left' : 'right'}
                                    className={column.className}
                                    aria-sort={
                                        sortBy === column.key
                                            ? sortDirection === 'asc'
                                                ? 'ascending'
                                                : 'descending'
                                            : 'none'
                                    }
                                >
                                    <Button
                                        size="sm"
                                        className="h-auto gap-1.5 whitespace-normal"
                                        disabled={usageLoading}
                                        onClick={() => sortModels(column.key)}
                                        data-attr={`models-usage-sort-${column.key}`}
                                    >
                                        <span>{column.label}</span>
                                        {sortBy === column.key ? (
                                            sortDirection === 'asc' ? (
                                                <IconArrowUp className="size-3" />
                                            ) : (
                                                <IconArrowDown className="size-3" />
                                            )
                                        ) : (
                                            <IconSort className="size-3 opacity-50" />
                                        )}
                                    </Button>
                                </TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {usage.models.map((row) => {
                            const nodeId = row.saved_query_id ? savedQueryIdToNodeId[row.saved_query_id] : undefined
                            return (
                                <TableRow key={row.saved_query_id ?? 'deleted'}>
                                    <TableCell
                                        expand
                                        className="min-w-32 max-w-96 break-all @min-[48rem]/main-content:min-w-40"
                                    >
                                        {row.deleted || !nodeId ? (
                                            <Text variant="muted" render={<span />}>
                                                {row.name}
                                                {row.deleted ? ' (deleted)' : ''}
                                            </Text>
                                        ) : (
                                            <LinkPrimitive
                                                className="font-medium text-link-primary hover:underline"
                                                to={urls.nodeDetail(nodeId)}
                                                onClick={openModel}
                                                data-attr="models-usage-open-model"
                                            >
                                                {row.name}
                                            </LinkPrimitive>
                                        )}
                                    </TableCell>
                                    {showEngineColumns ? (
                                        [
                                            DataModelingUsageListEngine.Clickhouse,
                                            DataModelingUsageListEngine.ManagedWarehouse,
                                        ].map((engine) => {
                                            const readBytes = engineBytes(row, engine)
                                            return (
                                                <TableCell
                                                    key={engine}
                                                    align="right"
                                                    className="whitespace-nowrap tabular-nums"
                                                >
                                                    {readBytes === null ? (
                                                        <UsageNotAvailable context="model" />
                                                    ) : (
                                                        humanizeBytes(readBytes)
                                                    )}
                                                </TableCell>
                                            )
                                        })
                                    ) : (
                                        <TableCell align="right" className="whitespace-nowrap tabular-nums">
                                            {row.read_bytes === null ? (
                                                <UsageNotAvailable context="model" />
                                            ) : (
                                                humanizeBytes(row.read_bytes)
                                            )}
                                        </TableCell>
                                    )}
                                    <TableCell
                                        align="right"
                                        className="hidden whitespace-nowrap tabular-nums @min-[48rem]/main-content:table-cell"
                                    >
                                        {row.cpu_microseconds === null ? (
                                            <UsageNotAvailable context="model" />
                                        ) : (
                                            humanFriendlyDuration(row.cpu_microseconds / 1_000_000)
                                        )}
                                    </TableCell>
                                    <TableCell align="right" className="whitespace-nowrap tabular-nums">
                                        {humanFriendlyNumber(row.runs)}
                                    </TableCell>
                                </TableRow>
                            )
                        })}
                    </TableBody>
                </Table>
            </CardContent>
            {usage.count > 0 ? (
                <CardFooter className="flex flex-row flex-wrap items-center justify-between gap-2 border-t border-border">
                    <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                        {firstRow}-{lastRow} of {pluralize(usage.count, 'model')}
                    </Text>
                    {pageCount > 1 ? (
                        <Pagination className="w-auto">
                            <PaginationContent>
                                <PaginationItem>
                                    <PaginationPrevious
                                        disabled={usageLoading || pageIndex === 0}
                                        onClick={() => setPage(page - 1)}
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
                                                disabled={usageLoading}
                                                onClick={() => setPage(item + 1)}
                                            >
                                                {item + 1}
                                            </PaginationButton>
                                        </PaginationItem>
                                    )
                                )}
                                <PaginationItem>
                                    <PaginationNext
                                        disabled={usageLoading || pageIndex === pageCount - 1}
                                        onClick={() => setPage(page + 1)}
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
