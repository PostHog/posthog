import './InsightsTable.scss'

import { useActions, useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartDisplayType, ItemMode } from '~/types'

import { entityFilterLogic } from '../../filters/ActionFilter/entityFilterLogic'
import { countryCodeToName } from '../WorldMap'
import { AggregationColumnItem, AggregationColumnTitle } from './columns/AggregationColumn'
import { BreakdownColumnItem, BreakdownColumnTitle } from './columns/BreakdownColumn'
import { SeriesCheckColumnItem, SeriesCheckColumnTitle } from './columns/SeriesCheckColumn'
import { SeriesColumnItem } from './columns/SeriesColumn'
import { ValueColumnItem, ValueColumnTitle } from './columns/ValueColumn'
import { WorldMapColumnItem, WorldMapColumnTitle } from './columns/WorldMapColumn'
import { AggregationType, insightsTableDataLogic } from './insightsTableDataLogic'
import { CalcColumnState } from './insightsTableLogic'

export interface InsightsTableProps {
    /** Whether this is just a legend instead of standalone insight viz. Default: false. */
    isLegend?: boolean
    /** Whether this is table is embedded in another card or whether it should be a card of its own. Default: false. */
    embedded?: boolean
    /** Key for the entityFilterLogic */
    filterKey: string
    canEditSeriesNameInline?: boolean
    /** (Un)checking series updates the insight via the API, so it should be disabled if updates aren't desired. */
    canCheckUncheckSeries?: boolean
    /* whether this table is below another insight or the insight is in table view */
    isMainInsightView?: boolean
}

export function InsightsTable({
    filterKey,
    isLegend = false,
    embedded = false,
    canEditSeriesNameInline = false,
    canCheckUncheckSeries = true,
    isMainInsightView = false,
}: InsightsTableProps): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { insightProps, isInDashboardContext, insight, hiddenLegendKeys } = useValues(insightLogic)
    const { toggleVisibility } = useActions(insightLogic)
    const {
        insightDataLoading,
        indexedResults,
        isNonTimeSeriesDisplay,
        compare,
        isTrends,
        display,
        interval,
        breakdownFilter,
        trendsFilter,
        isSingleSeries,
    } = useValues(trendsDataLogic(insightProps))
    const { aggregation, allowAggregation } = useValues(insightsTableDataLogic(insightProps))
    const { setAggregationType } = useActions(insightsTableDataLogic(insightProps))

    const handleSeriesEditClick = (item: IndexedTrendResult): void => {
        const entityFilter = entityFilterLogic.findMounted({
            typeKey: filterKey,
        })
        if (entityFilter) {
            entityFilter.actions.selectFilter(item.action)
            entityFilter.actions.showModal()
        }
    }

    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const hasCheckboxes =
        isLegend && (!display || ![ChartDisplayType.BoldNumber, ChartDisplayType.WorldMap].includes(display))
    // Build up columns to include. Order matters.
    const columns: LemonTableColumn<IndexedTrendResult, keyof IndexedTrendResult | undefined>[] = []

    columns.push({
        title: (
            <div className="flex items-center gap-4">
                {hasCheckboxes && (
                    <SeriesCheckColumnTitle
                        indexedResults={indexedResults}
                        canCheckUncheckSeries={canCheckUncheckSeries}
                        hiddenLegendKeys={hiddenLegendKeys}
                        toggleVisibility={toggleVisibility}
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
                    compare={compare}
                    handleEditClick={handleSeriesEditClick}
                    hasMultipleSeries={!isSingleSeries}
                />
            )
            return hasCheckboxes ? (
                <SeriesCheckColumnItem
                    item={item}
                    canCheckUncheckSeries={canCheckUncheckSeries}
                    hiddenLegendKeys={hiddenLegendKeys}
                    toggleVisibility={toggleVisibility}
                    label={<div className="ml-2 font-normal">{label}</div>}
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
                cohorts,
                formatPropertyValueForDisplay,
                item.breakdown_value,
                item.filter?.breakdown,
                item.filter?.breakdown_type,
                item.filter && isTrendsFilter(item.filter) && item.filter?.breakdown_histogram_bin_count !== undefined
            )

        columns.push({
            title: <BreakdownColumnTitle breakdownFilter={breakdownFilter} />,
            render: (_, item) => (
                <BreakdownColumnItem
                    item={item}
                    canCheckUncheckSeries={canCheckUncheckSeries}
                    isMainInsightView={isMainInsightView}
                    toggleVisibility={toggleVisibility}
                    formatItemBreakdownLabel={formatItemBreakdownLabel}
                />
            ),
            key: 'breakdown',
            sorter: (a, b) => {
                if (typeof a.breakdown_value === 'number' && typeof b.breakdown_value === 'number') {
                    return a.breakdown_value - b.breakdown_value
                }
                const labelA = formatItemBreakdownLabel(a)
                const labelB = formatItemBreakdownLabel(b)
                return labelA.localeCompare(labelB)
            },
        })
        if (isTrends && display === ChartDisplayType.WorldMap) {
            columns.push({
                title: <WorldMapColumnTitle />,
                render: (_, item: IndexedTrendResult) => <WorldMapColumnItem item={item} />,
                key: 'breakdown_addendum',
                sorter: (a, b) => {
                    const labelA = countryCodeToName[a.breakdown_value as string]
                    const labelB = countryCodeToName[b.breakdown_value as string]
                    return labelA.localeCompare(labelB)
                },
            })
        }
    }

    if (allowAggregation) {
        columns.push({
            title: (
                <AggregationColumnTitle
                    isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                    aggregation={aggregation}
                    setAggregationType={(state: CalcColumnState) => setAggregationType(state as AggregationType)}
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

    if (indexedResults?.length > 0 && indexedResults[0].data) {
        const valueColumns: LemonTableColumn<IndexedTrendResult, any>[] = indexedResults[0].data.map(
            (__, index: number) => ({
                title: (
                    <ValueColumnTitle
                        index={index}
                        indexedResults={indexedResults}
                        compare={compare}
                        interval={interval}
                    />
                ),
                render: (_, item: IndexedTrendResult) => (
                    <ValueColumnItem index={index} item={item} trendsFilter={trendsFilter} />
                ),
                key: `data-${index}`,
                sorter: (a, b) => (a.data[index] ?? NaN) - (b.data[index] ?? NaN),
                align: 'right',
            })
        )

        columns.push(...valueColumns)
    }

    return (
        <LemonTable
            id={isInDashboardContext ? insight.short_id : undefined}
            dataSource={
                isLegend || isMainInsightView ? indexedResults : indexedResults.filter((r) => !hiddenLegendKeys?.[r.id])
            }
            embedded={embedded}
            columns={columns}
            rowKey="id"
            loading={insightDataLoading}
            emptyState="No insight results"
            data-attr="insights-table-graph"
            useURLForSorting={insightMode !== ItemMode.Edit}
            rowRibbonColor={isLegend ? (item) => getSeriesColor(item.seriesIndex, compare || false) : undefined}
            firstColumnSticky
        />
    )
}
