import { useActions, useValues } from 'kea'
import { MouseEvent } from 'react'
import { createPortal } from 'react-dom'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams } from '~/types'

import { getChangeChartBarWidthPercent } from './changeChartData'
import { ChangeChartDisplayRow, changeChartLogic, HoveredChangeChartTooltip } from './changeChartLogic'

const tickClassName = 'absolute top-0 bottom-0 w-px bg-border'
const gridClassName = 'grid grid-cols-[7rem_minmax(8rem,12rem)_minmax(24rem,1fr)] gap-4 items-center px-3'
const TOOLTIP_WIDTH_PX = 360
const TOOLTIP_HEIGHT_PX = 110
const plotInsetClassName = 'absolute inset-y-0 left-[5rem] right-[5rem]'

function getGridClassName(showCurrentValue: boolean): string {
    return showCurrentValue
        ? gridClassName
        : 'grid grid-cols-[minmax(8rem,12rem)_minmax(24rem,1fr)] gap-4 items-center px-3'
}

const directionClasses = {
    up: {
        bar: 'bg-success-highlight',
        tip: 'bg-success',
        text: 'text-success',
        tooltipPanel: 'bg-success-highlight',
        tooltipValue: 'text-success',
    },
    down: {
        bar: 'bg-danger-highlight',
        tip: 'bg-danger',
        text: 'text-danger',
        tooltipPanel: 'bg-danger-highlight',
        tooltipValue: 'text-danger',
    },
    flat: {
        bar: 'bg-border',
        tip: 'bg-border-bold',
        text: 'text-secondary',
        tooltipPanel: 'bg-fill-secondary',
        tooltipValue: 'text-primary',
    },
    unavailable: {
        bar: 'bg-border',
        tip: 'bg-border-bold',
        text: 'text-secondary',
        tooltipPanel: 'bg-fill-secondary',
        tooltipValue: 'text-primary',
    },
} as const

function ChangeChartTooltip({
    hoveredTooltip,
    previousPeriodLabel,
    currentPeriodLabel,
}: {
    hoveredTooltip: HoveredChangeChartTooltip
    previousPeriodLabel: string
    currentPeriodLabel: string
}): JSX.Element {
    const directionClass = directionClasses[hoveredTooltip.row.rawRow.direction]

    const tooltip = (
        <div
            className="pointer-events-none fixed z-[var(--z-tooltip)]"
            style={{ left: hoveredTooltip.x, top: hoveredTooltip.y }}
        >
            <div className="pointer-events-none flex items-stretch overflow-hidden rounded-md border border-primary bg-surface-primary shadow-lg">
                <div className="min-w-40 border-r border-primary bg-surface-primary px-3 py-2 text-sm">
                    <div className="font-semibold text-primary">
                        {hoveredTooltip.row.previousValueLabel === 'No data'
                            ? 'No data'
                            : `${hoveredTooltip.row.previousValueLabel} ${hoveredTooltip.row.metricLabel}`.trim()}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-secondary">{previousPeriodLabel}</div>
                </div>
                <div className={`min-w-40 px-3 py-2 text-sm ${directionClass.tooltipPanel}`}>
                    <div className={`font-semibold ${directionClass.tooltipValue}`}>
                        {`${hoveredTooltip.row.currentValueLabel} ${hoveredTooltip.row.metricLabel}`.trim()}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-secondary">{currentPeriodLabel}</div>
                </div>
            </div>
        </div>
    )

    return createPortal(tooltip, document.body)
}

export function ChangeChartView({
    rows,
    axisLabels,
    domain,
    previousPeriodLabel,
    currentPeriodLabel,
    displayMode,
    hoveredTooltip,
    showCurrentValue,
    onHover,
    onLeave,
    onRowClick,
    scrollClassName,
}: {
    rows: ChangeChartDisplayRow[]
    axisLabels: string[]
    domain: number
    previousPeriodLabel: string
    currentPeriodLabel: string
    displayMode: 'relative' | 'absolute'
    hoveredTooltip: HoveredChangeChartTooltip | null
    showCurrentValue: boolean
    onHover: (event: MouseEvent, row: ChangeChartDisplayRow) => void
    onLeave: (key: string) => void
    onRowClick?: (row: ChangeChartDisplayRow) => void
    scrollClassName?: string
}): JSX.Element {
    return (
        <div
            className={`w-full overflow-x-auto ${scrollClassName ?? 'max-h-[32rem] overflow-y-auto'}`}
            data-attr="change-chart"
        >
            <div className="w-full min-w-[54rem]">
                <div className="sticky top-0 z-10 bg-surface-primary pb-2">
                    <div className={`${getGridClassName(showCurrentValue)} pt-3 text-xs text-tertiary`}>
                        {showCurrentValue ? <div>Current</div> : null}
                        <div>Breakdown</div>
                        <div className="relative h-8">
                            <div className={plotInsetClassName}>
                                <div className={`left-0 ${tickClassName}`} />
                                <div className={`left-1/4 ${tickClassName}`} />
                                <div className={`left-1/2 ${tickClassName}`} />
                                <div className={`left-3/4 ${tickClassName}`} />
                                <div className={`right-0 ${tickClassName}`} />
                                <div className="absolute inset-x-0 top-0 flex justify-between">
                                    {axisLabels.map((axisLabel) => (
                                        <span key={axisLabel}>{axisLabel}</span>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div>
                    {rows.map((row) => {
                        const width = getChangeChartBarWidthPercent(row.rawRow, domain, displayMode)
                        const directionClass = directionClasses[row.rawRow.direction]
                        const clickable = !!onRowClick
                        const isPositive = row.rawRow.direction === 'up'
                        const labelStyle =
                            row.rawRow.direction === 'unavailable'
                                ? { left: 'calc(50% + 0.5rem)' }
                                : isPositive
                                  ? { left: `calc(50% + ${width}% + 0.35rem)` }
                                  : { right: `calc(50% + ${width}% + 0.35rem)` }

                        return (
                            <div
                                key={row.key}
                                className={`${getGridClassName(showCurrentValue)} border-t border-primary py-2 first:border-t-0 ${clickable ? 'cursor-pointer hover:bg-fill-secondary' : ''}`}
                                onClick={clickable ? () => onRowClick(row) : undefined}
                                onMouseEnter={(event) => onHover(event, row)}
                                onMouseMove={(event) => onHover(event, row)}
                                onMouseLeave={() => onLeave(row.key)}
                            >
                                {showCurrentValue ? (
                                    <div className="font-semibold truncate">{row.currentValueLabel}</div>
                                ) : null}
                                <div className="truncate">{row.label}</div>
                                <div className="relative h-8">
                                    <div className={plotInsetClassName}>
                                        <div className={`left-0 ${tickClassName}`} />
                                        <div className={`left-1/4 ${tickClassName}`} />
                                        <div className={`left-1/2 ${tickClassName}`} />
                                        <div className={`left-3/4 ${tickClassName}`} />
                                        <div className={`right-0 ${tickClassName}`} />
                                        {width > 0 && (
                                            <div
                                                className={`absolute top-1/2 -translate-y-1/2 h-3 rounded-sm ${directionClass.bar}`}
                                                style={
                                                    isPositive
                                                        ? { left: '50%', width: `${width}%` }
                                                        : { left: `calc(50% - ${width}%)`, width: `${width}%` }
                                                }
                                            >
                                                <div
                                                    className={`absolute top-0 h-full w-3 ${directionClass.tip}`}
                                                    style={{
                                                        [isPositive ? 'right' : 'left']: 0,
                                                        clipPath: isPositive
                                                            ? 'polygon(0 0, 100% 50%, 0 100%)'
                                                            : 'polygon(100% 0, 0 50%, 100% 100%)',
                                                    }}
                                                />
                                            </div>
                                        )}
                                        <div
                                            className={`absolute top-1/2 -translate-y-1/2 text-xs font-medium whitespace-nowrap ${directionClass.text}`}
                                            style={labelStyle}
                                        >
                                            {row.changeLabel}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </div>
                {hoveredTooltip ? (
                    <ChangeChartTooltip
                        hoveredTooltip={hoveredTooltip}
                        previousPeriodLabel={previousPeriodLabel}
                        currentPeriodLabel={currentPeriodLabel}
                    />
                ) : null}
            </div>
        </div>
    )
}

export function ChangeChart({ showPersonsModal = true, context, inCardView }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = changeChartLogic({ insightProps, showPersonsModal, context, inCardView })
    const {
        axisLabels,
        changeChartDisplayRows,
        changeChartDomain,
        currentPeriodLabel,
        displayMode,
        hoveredTooltip,
        previousPeriodLabel,
        showCurrentValue,
    } = useValues(logic)
    const { clearHoveredTooltip, openRow, setHoveredTooltip } = useActions(logic)

    if (changeChartDisplayRows.length === 0) {
        return <InsightEmptyState />
    }

    const setTooltipPosition = (event: MouseEvent, row: ChangeChartDisplayRow): void => {
        const x = Math.min(event.clientX + 16, window.innerWidth - TOOLTIP_WIDTH_PX - 12)
        const y = Math.min(event.clientY + 16, window.innerHeight - TOOLTIP_HEIGHT_PX - 12)
        setHoveredTooltip(row, Math.max(12, x), Math.max(12, y))
    }

    return (
        <ChangeChartView
            rows={changeChartDisplayRows}
            axisLabels={axisLabels}
            domain={changeChartDomain}
            previousPeriodLabel={previousPeriodLabel}
            currentPeriodLabel={currentPeriodLabel}
            displayMode={displayMode}
            hoveredTooltip={hoveredTooltip}
            showCurrentValue={showCurrentValue}
            onHover={setTooltipPosition}
            onLeave={clearHoveredTooltip}
            onRowClick={openRow}
            scrollClassName={inCardView ? 'max-h-80 overflow-y-auto' : 'max-h-[32rem] overflow-y-auto'}
        />
    )
}
