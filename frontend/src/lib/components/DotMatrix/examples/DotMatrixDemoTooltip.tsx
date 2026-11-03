import './DotMatrixDemoTooltip.scss'

import type { DotMatrixCell } from '../types'
import { getDotMatrixSelectionSummary } from './dotMatrixDemoData'
import {
    DOT_MATRIX_MOCK_ACCOUNTS,
    getDotMatrixMockWeekLabel,
    DOT_MATRIX_MOCK_GROUPS,
    DOT_MATRIX_MOCK_PRODUCTS,
} from './dotMatrixMockFixtures'
import { type DotMatrixMockDatum, type DotMatrixMockDatasetName } from './dotMatrixMockTypes'

interface DotMatrixDemoTooltipProps {
    cell: DotMatrixCell<DotMatrixMockDatum>
    selectedSeries: string[]
    datasetName?: DotMatrixMockDatasetName
    rowLabel?: string
}

export function DotMatrixDemoTooltip({
    cell,
    selectedSeries,
    datasetName = 'product_activity',
    rowLabel,
}: DotMatrixDemoTooltipProps): JSX.Element {
    const account = DOT_MATRIX_MOCK_ACCOUNTS.find((item) => item.id === cell.rowKey)
    const series = selectedSeries.length
        ? selectedSeries
        : Object.keys(cell.values).filter((key) => cell.values[key] > 0)
    const { distinct, overlap } = getDotMatrixSelectionSummary(cell, series)
    const unit = datasetName === 'people' ? 'event' : 'user'
    const label = rowLabel ?? account?.name ?? cell.data[0]?.persons[0]?.email ?? cell.rowKey
    return (
        <div className="DotMatrixDemo__tooltip">
            <strong>{label}</strong>
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
                        <span>{`${cell.values[key] ?? 0} ${unit}${(cell.values[key] ?? 0) === 1 ? '' : 's'}`}</span>
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
                        <span className="text-muted">{`${overlap} ${overlap === 1 ? 'person used' : 'people used'} ${series.length === 2 ? 'both' : 'more than one selected product'}. ${overlap === 1 ? 'They count' : 'Each counts'} once.`}</span>
                    )}
                </>
            )}
        </div>
    )
}
