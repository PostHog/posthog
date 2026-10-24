import { useActions, useValues } from 'kea'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import {
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
import { modelsUsageLogic } from './modelsUsageLogic'

const PAGE_SIZE = 20

function engineBytes(row: ModelUsageRowApi, engine: string): number | null {
    return row.engines.find((item) => item.engine === engine)?.read_bytes ?? null
}

export function ModelsUsageByModelTable({
    savedQueryIdToNodeId,
}: {
    savedQueryIdToNodeId: Record<string, string>
}): JSX.Element | null {
    const { usage, usageLoading, page, managedWarehouseEnabled, selectedEngine } = useValues(modelsUsageLogic)
    const { setPage, openModel } = useActions(modelsUsageLogic)

    if (!usage || usage.overview.runs === 0) {
        return null
    }

    const pageCount = Math.max(Math.ceil(usage.count / PAGE_SIZE), 1)
    const pageIndex = page - 1
    const pageRange = getPaginationRange(pageCount, pageIndex)
    const firstRow = usage.count === 0 ? 0 : pageIndex * PAGE_SIZE + 1
    const lastRow = Math.min(firstRow + usage.models.length - 1, usage.count)
    const showEngineColumns = managedWarehouseEnabled && selectedEngine === DataModelingUsageListEngine.All

    return (
        <Card size="sm" className="min-w-0 gap-0">
            <CardHeader className="border-b border-border pb-3">
                <CardTitle role="heading" aria-level={3}>
                    Usage by model
                </CardTitle>
                <CardDescription>
                    Highest bytes read first. Review refresh schedules and query filters for models with high usage.
                </CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
                <Table fullWidth aria-busy={usageLoading}>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Model</TableHead>
                            {showEngineColumns ? (
                                <>
                                    <TableHead align="right">ClickHouse bytes</TableHead>
                                    <TableHead align="right">Managed warehouse bytes</TableHead>
                                </>
                            ) : (
                                <TableHead align="right">Bytes read</TableHead>
                            )}
                            <TableHead align="right" className="hidden @min-[48rem]/main-content:table-cell">
                                CPU time
                            </TableHead>
                            <TableHead align="right">Runs</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {usage.models.map((row) => {
                            const nodeId = row.saved_query_id ? savedQueryIdToNodeId[row.saved_query_id] : undefined
                            return (
                                <TableRow key={row.saved_query_id ?? 'deleted'}>
                                    <TableCell expand className="min-w-40 max-w-96 break-all">
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
                                                        <Text variant="muted" render={<span />}>
                                                            Not measured
                                                        </Text>
                                                    ) : (
                                                        humanizeBytes(readBytes)
                                                    )}
                                                </TableCell>
                                            )
                                        })
                                    ) : (
                                        <TableCell align="right" className="whitespace-nowrap tabular-nums">
                                            {row.read_bytes === null ? (
                                                <Text variant="muted" render={<span />}>
                                                    Not measured
                                                </Text>
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
                                            <Text variant="muted" render={<span />}>
                                                Not measured
                                            </Text>
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
