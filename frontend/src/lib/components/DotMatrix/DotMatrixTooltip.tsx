import { getDotMatrixActiveSeries } from './dotMatrixPresentation'
import type { DotMatrixCell, DotMatrixSeries } from './types'

interface DotMatrixTooltipProps<D> {
    cell: DotMatrixCell<D>
    rowLabel: string
    columnLabel: string
    series: DotMatrixSeries[]
}

export function DotMatrixTooltip<D>({ cell, rowLabel, columnLabel, series }: DotMatrixTooltipProps<D>): JSX.Element {
    const activeSeries = getDotMatrixActiveSeries(series, cell.values)
    return (
        <div className="DotMatrix__tooltip-content">
            <strong>{rowLabel}</strong>
            <span className="DotMatrix__tooltip-subtitle">{columnLabel}</span>
            {activeSeries.length ? (
                activeSeries.map((item) => (
                    <div key={item.key} className="DotMatrix__tooltip-value">
                        <span className="DotMatrix__tooltip-series">
                            <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
                                <circle cx="4" cy="4" r="4" fill={item.color} />
                            </svg>
                            <span>{item.label ?? item.key}</span>
                        </span>
                        <span>{cell.values[item.key]}</span>
                    </div>
                ))
            ) : (
                <span>{cell.values[''] ?? 'No activity in this cell.'}</span>
            )}
        </div>
    )
}
