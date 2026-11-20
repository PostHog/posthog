import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill'

import type { GroupUsageMetricApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { usageMetricCalculationLabel, usageMetricDisplayLabel, usageMetricSourceLabel } from './usageMetricLabels'

export interface QuillUsageMetricsTableProps {
    metrics: GroupUsageMetricApi[]
    loading: boolean
    restrictedReason: string | null
    onEdit: (metric: GroupUsageMetricApi) => void
    onDelete: (metric: GroupUsageMetricApi) => void
}

export function QuillUsageMetricsTable({
    metrics,
    loading,
    restrictedReason,
    onEdit,
    onDelete,
}: QuillUsageMetricsTableProps): JSX.Element {
    if (loading && metrics.length === 0) {
        return (
            <div className="flex w-full flex-col gap-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
            </div>
        )
    }

    return (
        <Table fullWidth className="rounded-md border border-border">
            <TableHeader>
                <TableRow>
                    <TableHead expand>Name</TableHead>
                    <TableHead>Format</TableHead>
                    <TableHead>Interval</TableHead>
                    <TableHead>Display</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Calculation</TableHead>
                    <TableHead />
                </TableRow>
            </TableHeader>
            {metrics.length === 0 ? (
                <TableEmpty>
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>No entries</EmptyTitle>
                        </EmptyHeader>
                    </Empty>
                </TableEmpty>
            ) : (
                <TableBody>
                    {metrics.map((metric) => (
                        <TableRow key={metric.id}>
                            <TableCell>{metric.name}</TableCell>
                            <TableCell>{metric.format}</TableCell>
                            <TableCell>{metric.interval}</TableCell>
                            <TableCell>{usageMetricDisplayLabel(metric)}</TableCell>
                            <TableCell>{usageMetricSourceLabel(metric)}</TableCell>
                            <TableCell>{usageMetricCalculationLabel(metric)}</TableCell>
                            <TableCell>
                                <DropdownMenu>
                                    <DropdownMenuTrigger
                                        render={
                                            <Button
                                                size="icon"
                                                aria-label="Usage metric actions"
                                                tooltip="Usage metric actions"
                                            />
                                        }
                                    >
                                        <IconEllipsis />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                        <DropdownMenuItem
                                            onClick={() => onEdit(metric)}
                                            disabledReason={restrictedReason}
                                        >
                                            Edit
                                        </DropdownMenuItem>
                                        <DropdownMenuItem
                                            variant="destructive"
                                            onClick={() => onDelete(metric)}
                                            disabledReason={restrictedReason}
                                        >
                                            Delete
                                        </DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            )}
        </Table>
    )
}
