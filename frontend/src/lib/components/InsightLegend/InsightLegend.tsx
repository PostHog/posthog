import './InsightLegend.scss'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { IconLegend } from 'lib/components/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getSeriesColor } from 'lib/colors'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { formatCompareLabel } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { ChartDisplayType, FilterType, InsightType } from '~/types'
import clsx from 'clsx'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { IndexedTrendResult } from 'scenes/trends/types'
import { useEffect, useRef } from 'react'

export interface InsightLegendProps {
    readOnly?: boolean
    horizontal?: boolean
    inCardView?: boolean
}

const trendTypeCanShowLegendDenyList = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsBarValue,
]

const insightViewCanShowLegendAllowList = [InsightType.TRENDS, InsightType.STICKINESS]

const shouldShowLegend = (filters: Partial<FilterType>, activeView: InsightType): boolean =>
    insightViewCanShowLegendAllowList.includes(activeView) &&
    !!filters.display &&
    !trendTypeCanShowLegendDenyList.includes(filters.display)

export function InsightLegendButton(): JSX.Element | null {
    const { filters, activeView } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)

    return shouldShowLegend(filters, activeView) ? (
        <Button className="InsightLegendButton" onClick={toggleInsightLegend}>
            <IconLegend />
            <span className="InsightLegendButton-title">{filters.show_legend ? 'Hide' : 'Show'} legend</span>
        </Button>
    ) : null
}

function shouldHighlightThisRow(
    hiddenLegendKeys: Record<string, boolean | undefined>,
    rowIndex: number,
    highlightedSeries: number | null
): boolean {
    const numberOfSeriesToSkip = Object.entries(hiddenLegendKeys).filter(
        ([key, isHidden]) => isHidden && Number(key) < rowIndex
    ).length
    const isSkipped = hiddenLegendKeys[rowIndex]
    return highlightedSeries !== null && !isSkipped && highlightedSeries + numberOfSeriesToSkip === rowIndex
}

function InsightLegendRow({
    hiddenLegendKeys,
    rowIndex,
    item,
    hasMultipleSeries,
    toggleVisibility,
    filters,
    highlighted,
}: {
    hiddenLegendKeys: Record<string, boolean | undefined>
    rowIndex: number
    item: IndexedTrendResult
    hasMultipleSeries: boolean
    toggleVisibility: (index: number) => void
    filters: Partial<FilterType>
    highlighted: boolean
}): JSX.Element {
    const highlightStyle: Record<string, any> = highlighted
        ? {
              style: { backgroundColor: getSeriesColor(item.id, false, true) },
          }
        : {}

    const rowRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (highlighted && rowRef.current) {
            rowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        }
    }, [highlighted])

    return (
        <div key={item.id} className="InsightLegendMenu-item p-2 w-full flex flex-row" ref={rowRef}>
            <div key={item.id} className={clsx('InsightLegendMenu-item p-2 w-full flex flex-row')} {...highlightStyle}>
                <LemonCheckbox
                    className="text-xs mr-4"
                    color={getSeriesColor(item.id, !!filters.compare)}
                    checked={!hiddenLegendKeys[rowIndex]}
                    onChange={() => toggleVisibility(rowIndex)}
                    fullWidth
                    label={
                        <InsightLabel
                            key={item.id}
                            seriesColor={getSeriesColor(item.id, !!filters.compare)}
                            action={item.action}
                            fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                            hasMultipleSeries={hasMultipleSeries}
                            breakdownValue={item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()}
                            compareValue={filters.compare ? formatCompareLabel(item) : undefined}
                            pillMidEllipsis={item?.filter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
                            hideIcon
                        />
                    }
                />
                {filters.display === ChartDisplayType.ActionsPie && (
                    <div className={'text-muted'}>{formatAggregationAxisValue(filters, item.aggregated_value)}</div>
                )}
            </div>
        </div>
    )
}

export function InsightLegend({ horizontal, inCardView, readOnly = false }: InsightLegendProps): JSX.Element | null {
    const { insightProps, filters, highlightedSeries, activeView } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, hiddenLegendKeys } = useValues(logic)
    const { toggleVisibility } = useActions(logic)

    return shouldShowLegend(filters, activeView) ? (
        <div
            className={clsx('InsightLegendMenu', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': readOnly,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="InsightLegendMenu-scroll">
                {indexedResults &&
                    indexedResults.map((item, index) => (
                        <InsightLegendRow
                            key={index}
                            hiddenLegendKeys={hiddenLegendKeys}
                            item={item}
                            rowIndex={index}
                            hasMultipleSeries={indexedResults.length > 1}
                            highlighted={shouldHighlightThisRow(hiddenLegendKeys, index, highlightedSeries)}
                            toggleVisibility={toggleVisibility}
                            filters={filters}
                        />
                    ))}
            </div>
        </div>
    ) : null
}
