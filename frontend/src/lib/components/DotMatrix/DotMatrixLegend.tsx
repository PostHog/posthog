import clsx from 'clsx'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { toggleDotMatrixSeries } from './dotMatrixData'
import { getDotMatrixGroups } from './dotMatrixPresentation'
import { DotMatrixScaleKey } from './DotMatrixScaleKey'
import type { DotMatrixCountBin, DotMatrixGroup, DotMatrixLegendLabels, DotMatrixSeries } from './types'

interface DotMatrixLegendProps {
    series: DotMatrixSeries[]
    groups: DotMatrixGroup[]
    mode: 'dots' | 'count'
    sizeThresholds: number[]
    countScale?: DotMatrixCountBin[]
    selectedSeries: string[]
    onSelectedSeriesChange?: (keys: string[]) => void
    labels?: DotMatrixLegendLabels
}

export function DotMatrixLegend({
    series,
    groups,
    mode,
    sizeThresholds,
    countScale,
    selectedSeries,
    onSelectedSeriesChange,
    labels,
}: DotMatrixLegendProps): JSX.Element {
    const itemLabel = labels?.itemLabel ?? 'series'
    const legendGroups = getDotMatrixGroups(series, groups)
    const filtering = selectedSeries.length > 0

    return (
        <div className="DotMatrix__legend">
            {legendGroups.map((group) => (
                <div key={group.key} className="DotMatrix__legend-row">
                    {group.label && <span className="DotMatrix__legend-group">{group.label}</span>}
                    <div className="DotMatrix__legend-items">
                        {group.series.map((item) => {
                            const itemClassName = clsx(
                                'DotMatrix__legend-item',
                                filtering && !selectedSeries.includes(item.key) && 'DotMatrix__legend-item--muted',
                                selectedSeries.includes(item.key) && 'DotMatrix__legend-item--selected'
                            )
                            const icon = (
                                <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">
                                    <circle cx="4.5" cy="4.5" r="4.5" fill={item.color} />
                                </svg>
                            )
                            return onSelectedSeriesChange ? (
                                <LemonButton
                                    key={item.key}
                                    className={itemClassName}
                                    size="xsmall"
                                    type="tertiary"
                                    aria-pressed={selectedSeries.includes(item.key)}
                                    data-attr="dot-matrix-series"
                                    onClick={(event) =>
                                        onSelectedSeriesChange(
                                            toggleDotMatrixSeries(selectedSeries, item.key, event.shiftKey)
                                        )
                                    }
                                    icon={icon}
                                >
                                    {item.label ?? item.key}
                                </LemonButton>
                            ) : (
                                <span key={item.key} className={clsx(itemClassName, 'DotMatrix__legend-item--static')}>
                                    {icon}
                                    <span>{item.label ?? item.key}</span>
                                </span>
                            )
                        })}
                    </div>
                </div>
            ))}
            <div className="DotMatrix__legend-footer">
                {filtering ? (
                    <div className="DotMatrix__selection">
                        <span className="DotMatrix__selection-label">
                            {labels?.selectionLabel?.(selectedSeries.length, mode) ??
                                `Showing ${selectedSeries.length} ${itemLabel}`}
                        </span>
                        {onSelectedSeriesChange && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => onSelectedSeriesChange([])}
                                data-attr="dot-matrix-show-all"
                            >
                                Show all
                            </LemonButton>
                        )}
                        {onSelectedSeriesChange && (
                            <span>{labels?.hint ?? `Shift-click to add or remove a ${itemLabel}.`}</span>
                        )}
                    </div>
                ) : (
                    onSelectedSeriesChange && (
                        <span>{labels?.hint ?? `Click a ${itemLabel} to filter. Shift-click to add more.`}</span>
                    )
                )}
                {labels?.footer ?? (
                    <DotMatrixScaleKey
                        mode={mode}
                        sizeThresholds={sizeThresholds}
                        countScale={countScale}
                        labels={labels}
                    />
                )}
            </div>
        </div>
    )
}
