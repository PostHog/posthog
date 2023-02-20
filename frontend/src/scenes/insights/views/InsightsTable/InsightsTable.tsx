import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { ChartDisplayType, IntervalType, ItemMode, TrendsFilterType } from '~/types'
import { CalcColumnState, insightsTableLogic } from './insightsTableLogic'
import { IndexedTrendResult } from 'scenes/trends/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { entityFilterLogic } from '../../filters/ActionFilter/entityFilterLogic'
import './InsightsTable.scss'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { countryCodeToName } from '../WorldMap'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { isFilterWithDisplay, isTrendsFilter } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import { SeriesCheckColumnTitle, SeriesCheckColumnItem } from './columns/SeriesCheckColumn'
import { SeriesColumnItem } from './columns/SeriesColumn'
import { BreakdownColumnTitle, BreakdownColumnItem } from './columns/BreakdownColumn'
import { WorldMapColumnTitle, WorldMapColumnItem } from './columns/WorldMapColumn'
import { AggregationColumnItem, AggregationColumnTitle } from './columns/AggregationColumn'
import { ValueColumnItem, ValueColumnTitle } from './columns/ValueColumn'
import { AggregationType, insightsTableDataLogic } from './insightsTableDataLogic'
import { BreakdownFilter, TrendsFilter } from '~/queries/schema'

interface InsightsTableProps {
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

export function InsightsTableDataExploration({ filterKey, ...rest }: InsightsTableProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isNonTimeSeriesDisplay, compare, isTrends, display, interval, breakdown, trendsFilter } = useValues(
        insightDataLogic(insightProps)
    )
    const { aggregation, allowAggregation } = useValues(insightsTableDataLogic(insightProps))
    const { setAggregationType } = useActions(insightsTableDataLogic(insightProps))

    const handleSeriesEditClick = (item: IndexedTrendResult): void => {
        const typeKey = `${filterKey}_data_exploration`
        const entityFilter = entityFilterLogic.findMounted({
            typeKey,
        })
        if (entityFilter) {
            entityFilter.actions.selectFilter(item.action)
            entityFilter.actions.showModal()
        }
    }
    return (
        <InsightsTableComponent
            isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
            compare={!!compare}
            isTrends={isTrends}
            trendsFilter={trendsFilter}
            display={display}
            interval={interval}
            breakdown={breakdown}
            allowAggregation={allowAggregation}
            aggregation={aggregation}
            setAggregationType={(state: CalcColumnState) => setAggregationType(state as AggregationType)}
            handleSeriesEditClick={handleSeriesEditClick}
            {...rest}
        />
    )
}

export function InsightsTable({ filterKey, ...rest }: InsightsTableProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(trendsLogic(insightProps))
    const hasMathUniqueFilter = !!(
        filters.actions?.find(({ math }) => math === 'dau') || filters.events?.find(({ math }) => math === 'dau')
    )
    const logic = insightsTableLogic({ hasMathUniqueFilter, filters })
    const { calcColumnState, showTotalCount } = useValues(logic)
    const { setCalcColumnState } = useActions(logic)

    const isNonTimeSeriesDisplay =
        isFilterWithDisplay(filters) && !!filters.display && NON_TIME_SERIES_DISPLAY_TYPES.includes(filters.display)

    const handleSeriesEditClick = (item: IndexedTrendResult): void => {
        const typeKey = filterKey
        const entityFilter = entityFilterLogic.findMounted({
            typeKey,
        })
        if (entityFilter) {
            entityFilter.actions.selectFilter(item.action)
            entityFilter.actions.showModal()
        }
    }

    return (
        <InsightsTableComponent
            isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
            compare={isTrendsFilter(filters) && !!filters.compare}
            isTrends={isTrendsFilter(filters)}
            trendsFilter={{
                aggregation_axis_format: (filters as TrendsFilterType).aggregation_axis_format,
                aggregation_axis_prefix: (filters as TrendsFilterType).aggregation_axis_prefix,
                aggregation_axis_postfix: (filters as TrendsFilterType).aggregation_axis_postfix,
            }}
            display={(filters as TrendsFilterType).display}
            interval={(filters as TrendsFilterType).interval}
            breakdown={{
                breakdown: filters.breakdown,
            }}
            allowAggregation={!!showTotalCount}
            aggregation={calcColumnState}
            setAggregationType={setCalcColumnState}
            handleSeriesEditClick={handleSeriesEditClick}
            {...rest}
        />
    )
}

export type InsightsTableComponentProps = Omit<InsightsTableProps, 'filterKey'> & {
    isTrends: boolean
    trendsFilter?: TrendsFilter | null
    display?: ChartDisplayType
    interval?: IntervalType
    breakdown?: BreakdownFilter
    isNonTimeSeriesDisplay: boolean
    compare?: boolean
    allowAggregation: boolean
    aggregation: CalcColumnState
    setAggregationType: (state: CalcColumnState) => void
    handleSeriesEditClick: (item: IndexedTrendResult) => void
}

export function InsightsTableComponent({
    isLegend = false,
    embedded = false,
    canEditSeriesNameInline = false,
    canCheckUncheckSeries = true,
    isMainInsightView = false,
    isNonTimeSeriesDisplay,
    isTrends,
    trendsFilter,
    display,
    interval,
    breakdown,
    compare,
    allowAggregation,
    aggregation,
    setAggregationType,
    handleSeriesEditClick,
}: InsightsTableComponentProps): JSX.Element | null {
    const { insightProps, isInDashboardContext, insight } = useValues(insightLogic)
    const { insightMode } = useValues(insightSceneLogic)
    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const { indexedResults, hiddenLegendKeys, resultsLoading } = useValues(trendsLogic(insightProps))
    const { toggleVisibility } = useActions(trendsLogic(insightProps))

    // Build up columns to include. Order matters.
    const columns: LemonTableColumn<IndexedTrendResult, keyof IndexedTrendResult | undefined>[] = []

    if (isLegend) {
        columns.push({
            title: (
                <SeriesCheckColumnTitle
                    indexedResults={indexedResults}
                    canCheckUncheckSeries={canCheckUncheckSeries}
                    hiddenLegendKeys={hiddenLegendKeys}
                    toggleVisibility={toggleVisibility}
                />
            ),
            render: (_, item) => (
                <SeriesCheckColumnItem
                    item={item}
                    canCheckUncheckSeries={canCheckUncheckSeries}
                    hiddenLegendKeys={hiddenLegendKeys}
                    compare={compare}
                    toggleVisibility={toggleVisibility}
                />
            ),
            width: 0,
        })
    }

    columns.push({
        title: 'Series',
        render: (_, item) => (
            <SeriesColumnItem
                item={item}
                indexedResults={indexedResults}
                canEditSeriesNameInline={canEditSeriesNameInline}
                compare={compare}
                handleEditClick={handleSeriesEditClick}
            />
        ),
        key: 'label',
        sorter: (a, b) => {
            const labelA = a.action?.name || a.label || ''
            const labelB = b.action?.name || b.label || ''
            return labelA.localeCompare(labelB)
        },
    })

    if (breakdown?.breakdown) {
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
            title: <BreakdownColumnTitle breakdown={breakdown?.breakdown} />,
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
                    setAggregationType={setAggregationType}
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
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            loading={resultsLoading}
            emptyState="No insight results"
            data-attr="insights-table-graph"
            className="insights-table"
            useURLForSorting={insightMode !== ItemMode.Edit}
        />
    )
}
