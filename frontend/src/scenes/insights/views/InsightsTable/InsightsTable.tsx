import './InsightsTable.scss'

import { useActions, useValues } from 'kea'
import { compare as compareFn } from 'natural-orderby'
import { useMemo } from 'react'

import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/geography/country'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { isValidBreakdown } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { entityFilterLogic } from '../../filters/ActionFilter/entityFilterLogic'
import { AggregationColumnItem, AggregationColumnTitle } from './columns/AggregationColumn'
import { BreakdownColumnItem, BreakdownColumnTitle, MultipleBreakdownColumnTitle } from './columns/BreakdownColumn'
import { ColorCustomizationColumnItem, ColorCustomizationColumnTitle } from './columns/ColorCustomizationColumn'
import { SeriesCheckColumnItem, SeriesCheckColumnTitle } from './columns/SeriesCheckColumn'
import { SeriesColumnItem } from './columns/SeriesColumn'
import { ValueColumnItem, ValueColumnTitle } from './columns/ValueColumn'
import { WorldMapColumnItem, WorldMapColumnTitle } from './columns/WorldMapColumn'
import { AggregationType, insightsTableDataLogic } from './insightsTableDataLogic'

export type CalcColumnState = 'total' | 'average' | 'median'

export interface InsightsTableProps {
    /** Key for the entityFilterLogic */
    filterKey: string
    /**
     * Whether this is just a legend instead of standalone insight viz.
     * @default false
     */
    isLegend?: boolean
    /**
     * Whether this is table is embedded in another card or whether it should be a card of its own.
     * @default false
     */
    embedded?: boolean
    /** @default false */
    canEditSeriesNameInline?: boolean
    seriesNameTooltip?: string
    /**
     * (Un)checking series updates the insight via the API, so it should be disabled if updates aren't desired.
     *  @default true
     */
    canCheckUncheckSeries?: boolean
    /**
     * Whether this table is below another insight or the insight is in table view.
     * @default false
     */
    isMainInsightView?: boolean
    /** Whether the insight is in edit mode. */
    editMode?: boolean
}

export function InsightsTable({
    filterKey,
    isLegend = false,
    embedded = false,
    canEditSeriesNameInline = false,
    seriesNameTooltip,
    canCheckUncheckSeries = true,
    isMainInsightView = false,
    editMode,
}: InsightsTableProps): JSX.Element {
    const { insightProps, isInDashboardContext, insight, editingDisabledReason } = useValues(insightLogic)
    const {
        insightDataLoading,
        indexedResults,
        isNonTimeSeriesDisplay,
        compareFilter,
        isTrends,
        isStickiness,
        display,
        interval,
        breakdownFilter,
        trendsFilter,
        isSingleSeries,
        getTrendsColor,
        getTrendsHidden,
        insightData,
    } = useValues(trendsDataLogic(insightProps))
    const { toggleResultHidden, toggleAllResultsHidden } = useActions(trendsDataLogic(insightProps))
    const { aggregation, allowAggregation } = useValues(insightsTableDataLogic(insightProps))
    const { setDetailedResultsAggregationType } = useActions(insightsTableDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)

    const handleSeriesEditClick = (item: IndexedTrendResult): void => {
        const entityFilter = entityFilterLogic.findMounted({
            typeKey: filterKey,
        })
        if (entityFilter) {
            entityFilter.actions.selectFilter(item.action)
            entityFilter.actions.showModal()
        }
    }

    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const hasCheckboxes =
        isLegend &&
        (!display ||
            ![ChartDisplayType.BoldNumber, ChartDisplayType.WorldMap, ChartDisplayType.CalendarHeatmap].includes(
                display
            ))
    // Build up columns to include. Order matters.
    const columns: LemonTableColumn<IndexedTrendResult, keyof IndexedTrendResult | undefined>[] = []

    columns.push({
        title: (
            <div className="flex items-center gap-4">
                {hasCheckboxes && (
                    <SeriesCheckColumnTitle
                        indexedResults={indexedResults}
                        canCheckUncheckSeries={canCheckUncheckSeries}
                        getTrendsHidden={getTrendsHidden}
                        toggleAllResultsHidden={toggleAllResultsHidden}
                        disabledReason={editingDisabledReason}
                    />
                )}
                <span>Series</span>
            </div>
        ),
        render: (_, item) => {
            const label = (
                <SeriesColumnItem
                    item={item}
                    indexedResults={indexedResults}
                    canEditSeriesNameInline={canEditSeriesNameInline}
                    seriesNameTooltip={seriesNameTooltip}
                    handleEditClick={handleSeriesEditClick}
                    hasMultipleSeries={!isSingleSeries}
                    hasBreakdown={isValidBreakdown(breakdownFilter)}
                />
            )
            return hasCheckboxes ? (
                <SeriesCheckColumnItem
                    item={item}
                    canCheckUncheckSeries={canCheckUncheckSeries}
                    isHidden={getTrendsHidden(item)}
                    toggleResultHidden={toggleResultHidden}
                    label={<div className="ml-2 font-normal">{label}</div>}
                    disabledReason={editingDisabledReason}
                />
            ) : (
                label
            )
        },
        key: 'label',
        sorter: (a, b) => {
            const labelA = a.action?.name || a.label || ''
            const labelB = b.action?.name || b.label || ''
            return labelA.localeCompare(labelB)
        },
    })

    if (breakdownFilter?.breakdown) {
        const formatItemBreakdownLabel = (item: IndexedTrendResult): string =>
            formatBreakdownLabel(
                item.breakdown_value,
                breakdownFilter,
                allCohorts?.results,
                formatPropertyValueForDisplay
            )

        columns.push({
            title: <BreakdownColumnTitle breakdownFilter={breakdownFilter} />,
            render: (_, item) => {
                return <BreakdownColumnItem item={item} formatItemBreakdownLabel={formatItemBreakdownLabel} />
            },
            key: 'breakdown',
            sorter: (a, b) => {
                if (typeof a.breakdown_value === 'number' && typeof b.breakdown_value === 'number') {
                    return a.breakdown_value - b.breakdown_value
                }
                const labelA = formatItemBreakdownLabel(a)
                const labelB = formatItemBreakdownLabel(b)
                return compareFn()(labelA, labelB)
            },
        })

        if (isTrends && display === ChartDisplayType.WorldMap) {
            columns.push({
                title: <WorldMapColumnTitle />,
                render: (_, item: IndexedTrendResult) => <WorldMapColumnItem item={item} />,
                key: 'breakdown_addendum',
                sorter: (a, b) => {
                    const labelA = COUNTRY_CODE_TO_LONG_NAME[a.breakdown_value as string]
                    const labelB = COUNTRY_CODE_TO_LONG_NAME[b.breakdown_value as string]
                    return labelA.localeCompare(labelB)
                },
            })
        }
    } else if (breakdownFilter?.breakdowns) {
        breakdownFilter.breakdowns.forEach((breakdown, index) => {
            const formatItemBreakdownLabel = (item: IndexedTrendResult): string =>
                formatBreakdownLabel(
                    Array.isArray(item.breakdown_value) ? item.breakdown_value[index] : item.breakdown_value,
                    breakdownFilter,
                    allCohorts?.results,
                    formatPropertyValueForDisplay,
                    index
                )

            columns.push({
                title: (
                    <MultipleBreakdownColumnTitle>
                        {extractExpressionComment(breakdown.property?.toString())}
                    </MultipleBreakdownColumnTitle>
                ),
                render: (_, item) => {
                    return <BreakdownColumnItem item={item} formatItemBreakdownLabel={formatItemBreakdownLabel} />
                },
                key: `breakdown-${breakdown.property?.toString() || index}`,
                sorter: (a, b) => {
                    const leftValue = Array.isArray(a.breakdown_value) ? a.breakdown_value[index] : a.breakdown_value
                    const rightValue = Array.isArray(b.breakdown_value) ? b.breakdown_value[index] : b.breakdown_value

                    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
                        return leftValue - rightValue
                    }

                    const labelA = formatItemBreakdownLabel(a)
                    const labelB = formatItemBreakdownLabel(b)

                    return compareFn()(labelA, labelB)
                },
            })
        })
    }

    if (!isMainInsightView && !embedded) {
        columns.push({
            title: <ColorCustomizationColumnTitle />,
            render: (_, item) => <ColorCustomizationColumnItem item={item} />,
            key: 'color',
        })
    }

    if (allowAggregation) {
        columns.push({
            title: (
                <AggregationColumnTitle
                    isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                    aggregation={aggregation}
                    setAggregationType={(state: CalcColumnState) =>
                        setDetailedResultsAggregationType(state as AggregationType)
                    }
                />
            ),
            render: (_: any, item: IndexedTrendResult) => (
                <AggregationColumnItem
                    item={item}
                    isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                    aggregation={aggregation}
                    trendsFilter={trendsFilter}
                />
            ),

            sorter: (a, b) => (a.count || a.aggregated_value) - (b.count || b.aggregated_value),
            dataIndex: 'count',
            align: 'right',
        })
    }

    const valueColumns: LemonTableColumn<IndexedTrendResult, any>[] = useMemo(() => {
        // Don't show value columns for non-time-series displays like WorldMap and Heatmap
        if (display === ChartDisplayType.WorldMap || display === ChartDisplayType.CalendarHeatmap) {
            return []
        }

        const results = indexedResults?.[0]?.data
        if (!results?.length) {
            return []
        }

        const capitalizeFirstLetter = (str: string): string => str.charAt(0).toUpperCase() + str.slice(1)

        const dataSorter = (a: IndexedTrendResult, b: IndexedTrendResult, index: number): number => {
            const aValue = a.data[index] ?? NaN
            const bValue = b.data[index] ?? NaN

            if (isStickiness) {
                return aValue / a.count - bValue / b.count
            }

            return aValue - bValue
        }

        return results.map((_, index) => ({
            title: isStickiness ? (
                `${interval ? capitalizeFirstLetter(interval) : 'Day'} ${index + 1}`
            ) : (
                <ValueColumnTitle
                    index={index}
                    indexedResults={indexedResults}
                    compare={compareFilter?.compare}
                    interval={interval}
                    resolvedDateRange={insightData?.resolved_date_range}
                    timezone={timezone}
                    weekStartDay={weekStartDay}
                />
            ),
            render: (_, item: IndexedTrendResult) => {
                return <ValueColumnItem index={index} item={item} trendsFilter={trendsFilter} />
            },
            key: `data-${index}`,
            sorter: (a: IndexedTrendResult, b: IndexedTrendResult) => dataSorter(a, b, index),
            align: 'right',
        }))
    }, [indexedResults, trendsFilter, isStickiness, compareFilter?.compare, interval]) // oxlint-disable-line react-hooks/exhaustive-deps

    columns.push(...valueColumns)

    return (
        <LemonTable
            id={isInDashboardContext ? insight.short_id : undefined}
            dataSource={
                isLegend || isMainInsightView
                    ? indexedResults
                    : indexedResults.filter((dataset) => !getTrendsHidden(dataset))
            }
            embedded={embedded}
            columns={columns}
            rowKey="id"
            loading={insightDataLoading}
            disableTableWhileLoading={false}
            emptyState="No insight results"
            data-attr="insights-table-graph"
            useURLForSorting={!editMode}
            rowRibbonColor={
                isLegend
                    ? (item) => {
                          const isPrevious = !!item.compare && item.compare_label === 'previous'

                          const themeColor = getTrendsColor(item)
                          const mainColor = isPrevious ? `${themeColor}80` : themeColor

                          return mainColor
                      }
                    : undefined
            }
            firstColumnSticky
            maxHeaderWidth="20rem"
        />
    )
}
