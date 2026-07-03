import { useMemo } from 'react'

import { LemonButton, LemonSelect, LemonTable, Spinner } from '@posthog/lemon-ui'

import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'

import { NotebookDataframeResult } from '../pythonExecution'

type NotebookDataframeTableProps = {
    result: NotebookDataframeResult | null
    loading: boolean
    page: number
    pageSize: number
    /** Unknown-total mode: when set, Next is driven by this flag and no total is shown
     * (push-to-CH paging can't know the full count without an extra query). */
    hasMore?: boolean
    onNextPage: () => void
    onPreviousPage: () => void
    onPageSizeChange: (pageSize: number) => void
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

const formatCellValue = (value: unknown): string => {
    if (value === null || value === undefined) {
        return ''
    }
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    try {
        return JSON.stringify(value)
    } catch {
        return String(value)
    }
}

export const NotebookDataframeTable = ({
    result,
    loading,
    page,
    pageSize,
    hasMore,
    onNextPage,
    onPreviousPage,
    onPageSizeChange,
}: NotebookDataframeTableProps): JSX.Element => {
    const columns = useMemo<LemonTableColumn<Record<string, any>, keyof Record<string, any> | undefined>[]>(() => {
        return (
            result?.columns.map((column, index) => ({
                title: column,
                key: `${column}-${index}`,
                dataIndex: column,
                render: (value) => <span className="font-mono text-xs">{formatCellValue(value)}</span>,
            })) ?? []
        )
    }, [result?.columns])

    const rowsWithIndex = useMemo(() => {
        const baseIndex = (page - 1) * pageSize
        return (
            result?.rows.map((row, index) => ({
                ...row,
                __rowId: baseIndex + index,
            })) ?? []
        )
    }, [page, pageSize, result?.rows])

    const isUnknownTotal = hasMore !== undefined
    const rowCount = result?.rowCount ?? 0
    const rowsShown = result?.rows.length ?? 0
    const startIndex = rowsShown > 0 ? (page - 1) * pageSize + 1 : 0
    const endIndex = isUnknownTotal
        ? rowsShown > 0
            ? startIndex + rowsShown - 1
            : 0
        : rowCount > 0
          ? Math.min(page * pageSize, rowCount)
          : 0
    const hasPrevious = page > 1
    const hasNext = isUnknownTotal ? !!hasMore : endIndex < rowCount
    const isInitialLoading = loading && rowCount === 0
    const emptyState = isInitialLoading ? (
        <div className="flex items-center justify-center gap-2 py-6 text-xs text-muted">
            <Spinner className="text-base" />
            <span>Loading rows…</span>
        </div>
    ) : (
        'No rows to display.'
    )

    return (
        <div className="flex flex-col gap-2">
            <LemonTable
                className="border-b border-primary"
                data-attr="notebook-dataframe-table"
                columns={columns}
                dataSource={rowsWithIndex}
                loading={loading}
                embedded
                size="small"
                rowKey="__rowId"
                emptyState={emptyState}
                loadingSkeletonRows={pageSize}
            />
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                <div className="flex items-center gap-2 pl-3">
                    <span>Rows per page</span>
                    <LemonSelect
                        size="small"
                        value={pageSize}
                        onChange={(value) => onPageSizeChange(value ?? pageSize)}
                        options={PAGE_SIZE_OPTIONS.map((option) => ({
                            label: option.toString(),
                            value: option,
                        }))}
                    />
                </div>
                <div className="flex items-center gap-2 pr-2">
                    <span>
                        {isUnknownTotal
                            ? rowsShown === 0
                                ? 'No rows'
                                : `${startIndex}-${endIndex}`
                            : rowCount === 0
                              ? 'No rows'
                              : `${startIndex}-${endIndex} of ${rowCount}`}
                    </span>
                    <LemonButton
                        size="small"
                        onClick={onPreviousPage}
                        disabledReason={hasPrevious ? undefined : 'No previous page'}
                    >
                        Prev
                    </LemonButton>
                    <LemonButton
                        size="small"
                        onClick={onNextPage}
                        disabledReason={hasNext ? undefined : 'No next page'}
                    >
                        Next
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
