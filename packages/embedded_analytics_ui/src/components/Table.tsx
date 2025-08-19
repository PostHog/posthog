import React, { ReactNode } from 'react'
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { EmbedButton } from './ui/embedButton'
import { SelectRoot, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select'
import { EmbedSkeleton } from './ui/embedSkeleton'
import { cn } from '../utils'
import { formatNumber } from '../utils'
import type { TableResponse, TableColumn, TableRow, ErrorResponse } from '../types/schemas'

export interface TableProps {
    response?: TableResponse
    loading?: boolean
    error?: ErrorResponse
    className?: string
    onRowClick?: (row: TableRow) => void
    onSort?: (column: string, direction: 'asc' | 'desc') => void
    onPageChange?: (page: number) => void
    onPageSizeChange?: (pageSize: number) => void
    currentSort?: { column: string; direction: 'asc' | 'desc' }
    currentPage?: number
    pageSize?: number
}

interface TableHeaderProps {
    column: TableColumn
    currentSort?: { column: string; direction: 'asc' | 'desc' }
    onSort?: (column: string, direction: 'asc' | 'desc') => void
}

function TableHeader({ column, currentSort, onSort }: TableHeaderProps): ReactNode {
    const isSorted = currentSort?.column === column.key
    const isAsc = isSorted && currentSort?.direction === 'asc'
    const isDesc = isSorted && currentSort?.direction === 'desc'

    const handleSort = (): void => {
        if (!onSort || !column.sortable) {
            return
        }

        if (!isSorted || isDesc) {
            onSort(column.key, 'asc')
        } else {
            onSort(column.key, 'desc')
        }
    }

    return (
        <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
            <div
                className={cn(
                    'flex items-center gap-2',
                    column.sortable && onSort && 'cursor-pointer hover:text-foreground transition-colors'
                )}
                onClick={handleSort}
            >
                <span>{column.label}</span>
                {column.sortable && onSort && (
                    <div className="flex flex-col">
                        <ChevronUp
                            className={cn('h-3 w-3 -mb-1', isAsc ? 'text-foreground' : 'text-muted-foreground/50')}
                        />
                        <ChevronDown
                            className={cn('h-3 w-3', isDesc ? 'text-foreground' : 'text-muted-foreground/50')}
                        />
                    </div>
                )}
            </div>
        </th>
    )
}

interface TableRowProps {
    row: TableRow
    columns: TableColumn[]
    onClick?: (row: TableRow) => void
}

function TableRowComponent({ row, columns, onClick }: TableRowProps): ReactNode {
    const isClickable = onClick !== undefined

    const handleClick = (): void => {
        if (isClickable) {
            onClick(row)
        }
    }

    const formatCellValue = (value: any, column: TableColumn): ReactNode => {
        if (value === null || value === undefined) {
            return '-'
        }

        switch (column.type) {
            case 'number':
                return typeof value === 'number' ? formatNumber(value, 'number', true) : value
            case 'percentage':
                return typeof value === 'number' ? `${value.toFixed(1)}%` : value
            default:
                return String(value)
        }
    }

    return (
        <tr
            className={cn(
                'border-t border-border hover:bg-accent/50 transition-colors relative z-0',
                isClickable && 'cursor-pointer'
            )}
            onClick={handleClick}
        >
            {columns.map((column, index) => (
                <td
                    key={column.key}
                    className={cn(
                        'px-4 py-3 text-sm',
                        index === 0 && row.fillRatio != null && row.fillRatio > 0 && 'analytics-table-fill-cell'
                    )}
                    style={
                        index === 0 && row.fillRatio != null && row.fillRatio > 0
                            ? ({ '--ph-embed-fill-ratio': row.fillRatio } as React.CSSProperties)
                            : undefined
                    }
                >
                    {formatCellValue(row[column.key], column)}
                </td>
            ))}
        </tr>
    )
}

interface PaginationProps {
    currentPage: number
    totalItems: number
    pageSize: number
    onPageChange?: (page: number) => void
    onPageSizeChange?: (pageSize: number) => void
    hasNext: boolean
    hasPrevious: boolean
}

function Pagination({
    currentPage,
    totalItems,
    pageSize,
    onPageChange,
    onPageSizeChange,
    hasNext,
    hasPrevious,
}: PaginationProps): ReactNode {
    const totalPages = Math.ceil(totalItems / pageSize)
    const startItem = (currentPage - 1) * pageSize + 1
    const endItem = Math.min(currentPage * pageSize, totalItems)

    return (
        <div className="flex items-center justify-between px-4 py-3 border-t border-border">
            <div className="flex items-center gap-4">
                <span className="text-sm text-muted-foreground">
                    Showing {startItem}-{endItem} of {totalItems}
                </span>

                {onPageSizeChange && (
                    <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-foreground">Rows per page:</span>
                        <SelectRoot
                            value={pageSize.toString()}
                            onValueChange={(value) => onPageSizeChange(parseInt(value))}
                        >
                            <SelectTrigger className="w-16 h-8">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="10">10</SelectItem>
                                <SelectItem value="25">25</SelectItem>
                                <SelectItem value="50">50</SelectItem>
                                <SelectItem value="100">100</SelectItem>
                            </SelectContent>
                        </SelectRoot>
                    </div>
                )}
            </div>

            <div className="flex items-center gap-2">
                <EmbedButton
                    variant="outline"
                    size="sm"
                    onClick={() => onPageChange?.(currentPage - 1)}
                    disabled={!hasPrevious || !onPageChange}
                >
                    <ChevronLeft className="h-4 w-4" />
                </EmbedButton>

                <span className="text-sm text-muted-foreground px-2">
                    Page {currentPage} of {totalPages}
                </span>

                <EmbedButton
                    variant="outline"
                    size="sm"
                    onClick={() => onPageChange?.(currentPage + 1)}
                    disabled={!hasNext || !onPageChange}
                >
                    <ChevronRight className="h-4 w-4" />
                </EmbedButton>
            </div>
        </div>
    )
}

function TableSkeleton({ className }: { className?: string }): ReactNode {
    return (
        <div className={cn('analytics-metric-card', className)}>
            <div className="space-y-4">
                {/* Header skeleton */}
                <div className="grid grid-cols-4 gap-4 px-4 py-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <EmbedSkeleton key={i} className="h-4 w-20" />
                    ))}
                </div>

                {/* Rows skeleton */}
                {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="grid grid-cols-4 gap-4 px-4 py-3 border-t border-border">
                        {Array.from({ length: 4 }).map((_, j) => (
                            <EmbedSkeleton key={j} className="h-4 w-16" />
                        ))}
                    </div>
                ))}

                {/* Pagination skeleton */}
                <div className="flex items-center justify-between px-4 py-3 border-t border-border">
                    <EmbedSkeleton className="h-4 w-32" />
                    <div className="flex items-center gap-2">
                        <EmbedSkeleton className="h-8 w-8" />
                        <EmbedSkeleton className="h-4 w-16" />
                        <EmbedSkeleton className="h-8 w-8" />
                    </div>
                </div>
            </div>
        </div>
    )
}

function TableError({ error, className }: { error: ErrorResponse; className?: string }): ReactNode {
    return (
        <div className={cn('analytics-error', className)}>
            <p className="font-medium">Error loading table</p>
            <p className="text-xs mt-1">{error.error}</p>
            {error.details && <p className="text-xs mt-1 opacity-75">{error.details}</p>}
        </div>
    )
}

export function Table({
    response,
    loading = false,
    error,
    className,
    onRowClick,
    onSort,
    onPageChange,
    onPageSizeChange,
    currentSort,
    currentPage = 1,
    pageSize = 25,
}: TableProps): ReactNode {
    if (error) {
        return <TableError error={error} className={className} />
    }

    if (loading) {
        return <TableSkeleton className={className} />
    }

    if (!response || !response.columns || response.columns.length === 0) {
        return (
            <div className={cn('analytics-metric-card', className)}>
                <div className="p-8 text-center">
                    <p className="text-muted-foreground">No table data available</p>
                </div>
            </div>
        )
    }

    const hasNext = !!response.next
    const hasPrevious = !!response.previous

    return (
        <div className={cn('analytics-metric-card overflow-hidden', className)}>
            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead className="bg-muted/50">
                        <tr>
                            {response.columns.map((column) => (
                                <TableHeader
                                    key={column.key}
                                    column={column}
                                    currentSort={currentSort}
                                    onSort={onSort}
                                />
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {response.rows.map((row, index) => (
                            <TableRowComponent
                                key={`${row.breakdown_value}-${index}`}
                                row={row}
                                columns={response.columns}
                                onClick={onRowClick}
                            />
                        ))}
                    </tbody>
                </table>
            </div>

            <Pagination
                currentPage={currentPage}
                totalItems={response.count}
                pageSize={pageSize}
                onPageChange={onPageChange}
                onPageSizeChange={onPageSizeChange}
                hasNext={hasNext}
                hasPrevious={hasPrevious}
            />
        </div>
    )
}
