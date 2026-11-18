import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { NotebookDataframeResult } from '../pythonExecution'

export type NotebookJupyterDataframeProps = {
    result: NotebookDataframeResult
    totalRowCount: number | null
    page: number
    pageSize: number
    hasMore: boolean
    loading: boolean
    paginationDisabledReason?: string
    onNextPage: () => void
    onPreviousPage: () => void
}

function formatDataframeValue(value: unknown): string {
    if (value === null || value === undefined) {
        return 'None'
    }
    if (typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}

export function NotebookJupyterDataframe({
    result,
    totalRowCount,
    page,
    pageSize,
    hasMore,
    loading,
    paginationDisabledReason,
    onNextPage,
    onPreviousPage,
}: NotebookJupyterDataframeProps): JSX.Element {
    const firstRowIndex = (page - 1) * pageSize
    const rowCount = totalRowCount ?? firstRowIndex + result.rows.length
    const isPaged = hasMore || page > 1

    return (
        <div className="MarkdownNotebook__jupyter-dataframe" aria-busy={loading}>
            <div className="overflow-x-auto">
                <table>
                    <thead>
                        <tr>
                            <th />
                            {result.columns.map((column) => (
                                <th key={column}>{column}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className={loading ? 'opacity-50' : undefined}>
                        {result.rows.map((row, rowIndex) => (
                            <tr key={firstRowIndex + rowIndex}>
                                <th>{firstRowIndex + rowIndex}</th>
                                {result.columns.map((column) => {
                                    const value = formatDataframeValue(row[column])
                                    return (
                                        <td key={column} title={value}>
                                            {value}
                                        </td>
                                    )
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="MarkdownNotebook__jupyter-dataframe-summary">
                <span>
                    {humanFriendlyNumber(rowCount)}
                    {hasMore && totalRowCount === null ? '+' : ''} rows × {result.columns.length} columns
                </span>
                {isPaged ? (
                    <span className="flex items-center gap-1">
                        <LemonButton
                            size="xsmall"
                            onClick={onPreviousPage}
                            disabledReason={page <= 1 ? 'This is the first page' : paginationDisabledReason}
                            data-attr="notebook-jupyter-dataframe-previous"
                        >
                            Previous
                        </LemonButton>
                        <span>
                            Rows {humanFriendlyNumber(firstRowIndex)} to{' '}
                            {humanFriendlyNumber(firstRowIndex + result.rows.length - 1)}
                        </span>
                        <LemonButton
                            size="xsmall"
                            onClick={onNextPage}
                            disabledReason={!hasMore ? 'This is the last page' : paginationDisabledReason}
                            data-attr="notebook-jupyter-dataframe-next"
                        >
                            Next
                        </LemonButton>
                    </span>
                ) : null}
            </div>
        </div>
    )
}
