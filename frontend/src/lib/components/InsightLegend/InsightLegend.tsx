import './InsightLegend.scss'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { IconLegend } from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getSeriesColor } from 'lib/colors'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { formatCompareLabel } from 'scenes/insights/views/InsightsTable/columns/SeriesColumn'
import { ChartDisplayType, FilterType, InsightType } from '~/types'
import clsx from 'clsx'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { IndexedTrendResult } from 'scenes/trends/types'
import { useEffect, useRef } from 'react'
import { isFilterWithDisplay, isTrendsFilter } from 'scenes/insights/sharedUtils'

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
    isFilterWithDisplay(filters) &&
    !!filters.display &&
    !trendTypeCanShowLegendDenyList.includes(filters.display)

export function InsightLegendButton(): JSX.Element | null {
    const { filters, activeView } = useValues(insightLogic)
    const { toggleInsightLegend } = useActions(insightLogic)

    return shouldShowLegend(filters, activeView) && isFilterWithDisplay(filters) ? (
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
              style: { backgroundColor: getSeriesColor(item.seriesIndex, false, true) },
          }
        : {}

    const rowRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (highlighted && rowRef.current) {
            rowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        }
    }, [highlighted])

    const compare = isTrendsFilter(filters) && !!filters.compare

    return (
        <div key={item.id} className="InsightLegendMenu-item p-2 flex flex-row" ref={rowRef} {...highlightStyle}>
            <div className="grow">
                <LemonCheckbox
                    className="text-xs mr-4"
                    color={getSeriesColor(item.seriesIndex, compare)}
                    checked={!hiddenLegendKeys[rowIndex]}
                    onChange={() => toggleVisibility(rowIndex)}
                    fullWidth
                    label={
                        <InsightLabel
                            key={item.id}
                            seriesColor={getSeriesColor(item.seriesIndex, compare)}
                            action={item.action}
                            fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                            hasMultipleSeries={hasMultipleSeries}
                            breakdownValue={item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()}
                            compareValue={compare ? formatCompareLabel(item) : undefined}
                            pillMidEllipsis={item?.filter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
                            hideIcon
                        />
                    }
                />
            </div>
            {isTrendsFilter(filters) && filters.display === ChartDisplayType.ActionsPie && (
                <div className="text-muted grow-0">{formatAggregationAxisValue(filters, item.aggregated_value)}</div>
            )}
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
            className={clsx('InsightLegendMenu', 'flex overflow-auto border rounded', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': readOnly,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="grid grid-cols-1">
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
