import React from 'react'
import { Dropdown, Menu } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { BindLogic, useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'
import { cohortsModel } from '~/models/cohortsModel'
import { BreakdownKeyType, CohortType, FilterType, InsightShortId, IntervalType, TrendResult } from '~/types'
import { average, median, maybeAddCommasToInteger, capitalizeFirstLetter } from 'lib/utils'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { CalcColumnState, insightsTableLogic } from './insightsTableLogic'
import { DownOutlined, InfoCircleOutlined, EditOutlined } from '@ant-design/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DateDisplay } from 'lib/components/DateDisplay'
import { SeriesToggleWrapper } from './components/SeriesToggleWrapper'
import { ACTIONS_LINE_GRAPH_CUMULATIVE, ACTIONS_PIE_CHART, ACTIONS_TABLE } from 'lib/constants'
import { IndexedTrendResult } from 'scenes/trends/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'
import './InsightsTable.scss'
import clsx from 'clsx'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import stringWithWBR from 'lib/utils/stringWithWBR'

interface InsightsTableProps {
    /** Whether this is just a legend instead of standalone insight viz. Default: false. */
    isLegend?: boolean
    /** Whether this is table is embedded in another card or whether it should be a card of its own. Default: false. */
    embedded?: boolean
    showTotalCount?: boolean
    /** Key for the entityFilterLogic */
    filterKey: string
    canEditSeriesNameInline?: boolean
}

const CALC_COLUMN_LABELS: Record<CalcColumnState, string> = {
    total: 'Total Sum',
    average: 'Average',
    median: 'Median',
}

/**
 * InsightsTable for use in a dashboard.
 */
export function DashboardInsightsTable({
    filters,
    dashboardItemId,
}: {
    filters: FilterType
    dashboardItemId: InsightShortId
}): JSX.Element {
    return (
        <BindLogic logic={trendsLogic} props={{ dashboardItemId, filters }}>
            <InsightsTable showTotalCount filterKey={`dashboard_${dashboardItemId}`} embedded />
        </BindLogic>
    )
}

export function InsightsTable({
    isLegend = false,
    embedded = false,
    showTotalCount = false,
    filterKey,
    canEditSeriesNameInline,
}: InsightsTableProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { indexedResults, hiddenLegendKeys, filters, resultsLoading } = useValues(trendsLogic(insightProps))
    const { toggleVisibility, setFilters } = useActions(trendsLogic(insightProps))
    const { cohorts } = useValues(cohortsModel)
    const { reportInsightsTableCalcToggled } = useActions(eventUsageLogic)

    const _entityFilterLogic = entityFilterLogic({
        setFilters,
        filters,
        typeKey: filterKey,
    })
    const { showModal, selectFilter } = useActions(_entityFilterLogic)

    const hasMathUniqueFilter = !!(
        filters.actions?.find(({ math }) => math === 'dau') || filters.events?.find(({ math }) => math === 'dau')
    )
    const logic = insightsTableLogic({ hasMathUniqueFilter })
    const { calcColumnState } = useValues(logic)
    const { setCalcColumnState } = useActions(logic)

    const colorList = getChartColors('white', indexedResults.length, !!filters.compare)
    const showCountedByTag = !!indexedResults.find(({ action }) => action?.math && action.math !== 'total')

    const handleEditClick = (item: IndexedTrendResult): void => {
        if (canEditSeriesNameInline) {
            selectFilter(item.action)
            showModal()
        }
    }

    const calcColumnMenu = (
        <Menu>
            {Object.keys(CALC_COLUMN_LABELS).map((key) => (
                <Menu.Item
                    key={key}
                    onClick={(e) => {
                        setCalcColumnState(key as CalcColumnState)
                        reportInsightsTableCalcToggled(key)
                        e.domEvent.stopPropagation() // Prevent click here from affecting table sorting
                    }}
                >
                    {CALC_COLUMN_LABELS[key as CalcColumnState]}
                </Menu.Item>
            ))}
        </Menu>
    )

    // Build up columns to include. Order matters.
    const columns: LemonTableColumns<IndexedTrendResult> = []

    if (isLegend) {
        columns.push({
            render: function RenderCheckbox(_, item: IndexedTrendResult) {
                return (
                    <PHCheckbox
                        color={colorList[item.id]}
                        checked={!hiddenLegendKeys[item.id]}
                        onChange={() => toggleVisibility(item.id)}
                    />
                )
            },
            width: 0,
        })
    }

    columns.push({
        title: 'Series',
        render: function RenderLabel(_, item: IndexedTrendResult): JSX.Element {
            return (
                <div className="series-name-wrapper-col">
                    <InsightLabel
                        seriesColor={colorList[item.id]}
                        action={item.action}
                        fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                        hasMultipleSeries={indexedResults.length > 1}
                        showCountedByTag={showCountedByTag}
                        breakdownValue={item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()}
                        hideBreakdown
                        hideIcon
                        className={clsx({
                            editable: canEditSeriesNameInline,
                        })}
                        pillMaxWidth={165}
                        compareValue={filters.compare ? formatCompareLabel(item) : undefined}
                        onLabelClick={canEditSeriesNameInline ? () => handleEditClick(item) : undefined}
                    />
                    {canEditSeriesNameInline && (
                        <EditOutlined
                            title="Rename graph series"
                            className="edit-icon"
                            onClick={() => handleEditClick(item)}
                        />
                    )}
                </div>
            )
        },
        key: 'label',
        sorter: (a, b) => {
            const labelA = a.action?.name || a.label || ''
            const labelB = b.action?.name || b.label || ''
            return labelA.localeCompare(labelB)
        },
    })

    if (filters.breakdown) {
        columns.push({
            title: (
                <PropertyKeyInfo disableIcon disablePopover value={filters.breakdown.toString() || 'Breakdown Value'} />
            ),
            render: function RenderBreakdownValue(_, item: IndexedTrendResult) {
                const breakdownLabel = formatBreakdownLabel(cohorts, item.breakdown_value)
                return (
                    <SeriesToggleWrapper id={item.id} toggleVisibility={toggleVisibility}>
                        {breakdownLabel && <div title={breakdownLabel}>{stringWithWBR(breakdownLabel, 20)}</div>}
                    </SeriesToggleWrapper>
                )
            },
            key: 'breakdown',
            sorter: (a, b) => {
                const labelA = formatBreakdownLabel(cohorts, a.breakdown_value)
                const labelB = formatBreakdownLabel(cohorts, b.breakdown_value)
                return labelA.localeCompare(labelB)
            },
        })
    }

    if (indexedResults?.length > 0 && indexedResults[0].data) {
        const previousResult = !!filters.compare
            ? indexedResults.find((r) => r.compare_label === 'previous')
            : undefined
        const valueColumns: LemonTableColumn<IndexedTrendResult, any>[] = indexedResults[0].data.map(
            (__, index: number) => ({
                title: (
                    <DateDisplay
                        interval={(filters.interval as IntervalType) || 'day'}
                        date={(indexedResults[0].dates || indexedResults[0].days)[index]} // current
                        secondaryDate={
                            !!previousResult ? (previousResult.dates || previousResult.days)[index] : undefined
                        } // previous
                        hideWeekRange
                    />
                ),
                render: function RenderPeriod(_, item: IndexedTrendResult) {
                    return maybeAddCommasToInteger(item.data[index])
                },
                key: `data[${index}]`,
                sorter: (a, b) => a.data[index] - b.data[index],
                align: 'right',
            })
        )

        columns.push(...valueColumns)
    }

    if (showTotalCount) {
        columns.push({
            title: (
                <Dropdown overlay={calcColumnMenu}>
                    <span className="cursor-pointer">
                        {CALC_COLUMN_LABELS[calcColumnState]}
                        <DownOutlined className="ml-025" />
                    </span>
                </Dropdown>
            ),
            render: function RenderCalc(count: any, item: IndexedTrendResult) {
                if (calcColumnState === 'average') {
                    return average(item.data).toLocaleString()
                } else if (calcColumnState === 'median') {
                    return median(item.data).toLocaleString()
                } else if (
                    calcColumnState === 'total' &&
                    (filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE ||
                        filters.display === ACTIONS_TABLE ||
                        filters.display === ACTIONS_PIE_CHART)
                ) {
                    return (item.count || item.aggregated_value || 'Unknown').toLocaleString()
                }
                return (
                    <>
                        {count?.toLocaleString?.()}
                        {item.action && item.action?.math === 'dau' && (
                            <Tooltip title="Keep in mind this is just the sum of all values in the row, not the unique users across the entire time period (i.e. this number may contain duplicate users).">
                                <InfoCircleOutlined style={{ marginLeft: 4, color: 'var(--primary-alt)' }} />
                            </Tooltip>
                        )}
                    </>
                )
            },
            sorter: (a, b) => (a.count || a.aggregated_value) - (b.count || b.aggregated_value),
            dataIndex: 'count',
            align: 'right',
        })
    }

    return (
        <LemonTable
            dataSource={isLegend ? indexedResults : indexedResults.filter((r) => !hiddenLegendKeys?.[r.id])}
            embedded={embedded}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            loading={resultsLoading}
            emptyState="No insight results"
            data-attr="insights-table-graph"
            className="insights-table"
        />
    )
}

export function formatBreakdownLabel(cohorts?: CohortType[], breakdown_value?: BreakdownKeyType): string {
    if (breakdown_value && typeof breakdown_value == 'number') {
        return cohorts?.filter((c) => c.id == breakdown_value)[0]?.name || breakdown_value.toString()
    } else if (typeof breakdown_value == 'string') {
        return breakdown_value === 'nan' ? 'Other' : breakdown_value === '' ? 'None' : breakdown_value
    } else if (Array.isArray(breakdown_value)) {
        return breakdown_value.join('::')
    } else {
        return ''
    }
}

export function formatCompareLabel(trendResult: TrendResult): string {
    // label splitting ensures backwards compatibility for api results that don't contain the new compare_label
    const labels = trendResult.label.split(' - ')
    return capitalizeFirstLetter(trendResult.compare_label ?? labels?.[labels.length - 1] ?? 'current')
}
