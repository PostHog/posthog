import clsx from 'clsx'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { toggleDotMatrixSeries } from './dotMatrixData'
import type { DotMatrixCountBin, DotMatrixGroup, DotMatrixProps, DotMatrixSeries } from './types'

interface DotMatrixLegendProps {
    series: DotMatrixSeries[]
    groups: DotMatrixGroup[]
    mode: 'dots' | 'count'
    sizeThresholds: number[]
    countScale?: DotMatrixCountBin[]
    selectedSeries: string[]
    onSelectedSeriesChange?: (keys: string[]) => void
    labels?: Exclude<DotMatrixProps<Record<string, unknown>>['legend'], false>
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
    const legendGroups = [
        ...groups.map((group) => ({ ...group, items: series.filter((item) => item.group === group.key) })),
        { key: '', label: '', items: series.filter((item) => !groups.some((group) => group.key === item.group)) },
    ].filter((group) => group.items.length > 0)
    const filtering = selectedSeries.length > 0

    return (
        <div className="DotMatrix__legend">
            {legendGroups.map((group) => (
                <div key={group.key} className="DotMatrix__legend-row">
                    {group.label && <span className="DotMatrix__legend-group">{group.label}</span>}
                    <div className="DotMatrix__legend-items">
                        {group.items.map((item) => {
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
                            {labels?.selectionLabel?.(selectedSeries.length) ??
                                `Showing ${selectedSeries.length} ${itemLabel}`}
                        </span>
                        {onSelectedSeriesChange && (
                            <LemonButton
                                type="secondary"
                                size="xsmall"
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
                {labels?.footer ??
                    (mode === 'dots' ? (
                        <div className="DotMatrix__size-key">
                            <span>{labels?.valueLabel ?? 'Value'}</span>
                            {sizeThresholds.slice(0, 3).map((threshold, index) => (
                                <span className="DotMatrix__key-item" key={threshold}>
                                    <svg width="17" height="17" viewBox="0 0 17 17" aria-hidden="true">
                                        <circle cx="8.5" cy="8.5" r="2.6" fill="currentColor" />
                                        {index >= 1 && (
                                            <circle
                                                cx="8.5"
                                                cy="8.5"
                                                r="4.4"
                                                fill="none"
                                                stroke="currentColor"
                                                strokeWidth="1.2"
                                            />
                                        )}
                                        {index >= 2 && (
                                            <circle
                                                cx="8.5"
                                                cy="8.5"
                                                r="6.7"
                                                fill="none"
                                                stroke="currentColor"
                                                strokeWidth="1.2"
                                            />
                                        )}
                                    </svg>
                                    <b>{`${threshold}+`}</b>
                                </span>
                            ))}
                        </div>
                    ) : (
                        countScale && (
                            <div className="DotMatrix__count-key">
                                <span>{labels?.countLabel ?? 'Count'}</span>
                                {countScale.map((bin, index) => (
                                    <span className="DotMatrix__key-item" key={bin.min}>
                                        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                                            <rect width="14" height="14" rx="3" fill={bin.color} />
                                        </svg>
                                        <span>
                                            {bin.label ??
                                                (countScale[index + 1]
                                                    ? `${bin.min}-${countScale[index + 1].min - 1}`
                                                    : `${bin.min}+`)}
                                        </span>
                                    </span>
                                ))}
                            </div>
                        )
                    ))}
            </div>
        </div>
    )
}
