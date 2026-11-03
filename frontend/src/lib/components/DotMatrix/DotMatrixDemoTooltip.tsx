import {
    aggregateDotMatrixMockPeople,
    DOT_MATRIX_MOCK_ACCOUNTS,
    getDotMatrixMockWeekLabel,
    DOT_MATRIX_MOCK_GROUPS,
    DOT_MATRIX_MOCK_PRODUCTS,
    type DotMatrixMockDatum,
} from './mocks'
import type { DotMatrixCell } from './types'

interface DotMatrixDemoTooltipProps {
    cell: DotMatrixCell<DotMatrixMockDatum>
    selectedSeries: string[]
}

export function DotMatrixDemoTooltip({ cell, selectedSeries }: DotMatrixDemoTooltipProps): JSX.Element {
    const account = DOT_MATRIX_MOCK_ACCOUNTS.find((item) => item.id === cell.rowKey)
    const series = selectedSeries.length
        ? selectedSeries
        : Object.keys(cell.values).filter((key) => cell.values[key] > 0)
    const distinct = aggregateDotMatrixMockPeople(cell, series)
    const overlap = series.reduce((sum, key) => sum + (cell.values[key] ?? 0), 0) - distinct
    return (
        <div className="DotMatrixDemo__tooltip">
            <strong>{account?.name ?? cell.rowKey}</strong>
            <span className="text-muted">{getDotMatrixMockWeekLabel(cell.columnKey)}</span>
            {series.map((key) => {
                const index = DOT_MATRIX_MOCK_PRODUCTS.findIndex(([product]) => product === key)
                return (
                    <div key={key} className="DotMatrixDemo__tooltip-line">
                        <span>
                            <svg width="8" height="8" aria-hidden="true">
                                <circle
                                    cx="4"
                                    cy="4"
                                    r="4"
                                    fill={DOT_MATRIX_MOCK_GROUPS[Math.floor(Math.max(0, index) / 6)].color}
                                />
                            </svg>
                            <span>{DOT_MATRIX_MOCK_PRODUCTS[index]?.[1] ?? key}</span>
                        </span>
                        <span>{`${cell.values[key] ?? 0} ${(cell.values[key] ?? 0) === 1 ? 'user' : 'users'}`}</span>
                    </div>
                )
            })}
            {selectedSeries.length > 0 && (
                <>
                    <div className="DotMatrixDemo__tooltip-total">
                        <strong>Distinct users</strong>
                        <strong>{distinct}</strong>
                    </div>
                    {overlap > 0 && (
                        <span className="text-muted">{`${overlap} ${overlap === 1 ? 'person used' : 'people used'} both. ${overlap === 1 ? 'They count' : 'Each counts'} once.`}</span>
                    )}
                </>
            )}
        </div>
    )
}
