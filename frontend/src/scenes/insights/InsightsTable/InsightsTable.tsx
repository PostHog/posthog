import React from 'react'
import { Dropdown, Menu } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { BindLogic, useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { getSeriesColor } from 'lib/colors'
import { cohortsModel } from '~/models/cohortsModel'
import { BreakdownKeyType, ChartDisplayType, CohortType, IntervalType, TrendResult } from '~/types'
import { average, median, capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { CalcColumnState, insightsTableLogic } from './insightsTableLogic'
import { DownOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DateDisplay } from 'lib/components/DateDisplay'
import { SeriesToggleWrapper } from './components/SeriesToggleWrapper'
import { IndexedTrendResult } from 'scenes/trends/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { entityFilterLogic } from '../ActionFilter/entityFilterLogic'
import './InsightsTable.scss'
import clsx from 'clsx'
import { LemonTable, LemonTableColumn } from 'lib/components/LemonTable'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { LemonButton } from 'lib/components/LemonButton'
import { IconEdit } from 'lib/components/icons'
import { countryCodeToName } from '../WorldMap'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'

interface InsightsTableProps {
    /** Whether this is just a legend instead of standalone insight viz. Default: false. */
    isLegend?: boolean
    /** Whether this is table is embedded in another card or whether it should be a card of its own. Default: false. */
    embedded?: boolean
    showTotalCount?: boolean
    /** Key for the entityFilterLogic */
    filterKey: string
    canEditSeriesNameInline?: boolean
    /** (Un)checking series updates the insight via the API, so it should be disabled if updates aren't desired. */
    canCheckUncheckSeries?: boolean
    /* whether this table is below another insight or the insight is in table view */
    isMainInsightView?: boolean
}

const CALC_COLUMN_LABELS: Record<CalcColumnState, string> = {
    total: 'Total Sum',
    average: 'Average',
    median: 'Median',
}

/**
 * InsightsTable for use in a dashboard.
 */
export function DashboardInsightsTable(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    return (
        <BindLogic logic={trendsLogic} props={insightProps}>
            <InsightsTable showTotalCount filterKey={`dashboard_${insightProps.dashboardItemId}`} embedded />
        </BindLogic>
    )
}

export function InsightsTable({
    isLegend = false,
    embedded = false,
    showTotalCount = false,
    filterKey,
    canEditSeriesNameInline = false,
    canCheckUncheckSeries = true,
    isMainInsightView = false,
}: InsightsTableProps): JSX.Element | null {
    const { insightProps, isViewedOnDashboard, insight } = useValues(insightLogic)
    const { indexedResults, hiddenLegendKeys, filters, resultsLoading } = useValues(trendsLogic(insightProps))
    const { toggleVisibility, setFilters } = useActions(trendsLogic(insightProps))
    const { cohorts } = useValues(cohortsModel)
    const { reportInsightsTableCalcToggled } = useActions(eventUsageLogic)

    const hasMathUniqueFilter = !!(
        filters.actions?.find(({ math }) => math === 'dau') || filters.events?.find(({ math }) => math === 'dau')
    )
    const logic = insightsTableLogic({ hasMathUniqueFilter })
    const { calcColumnState } = useValues(logic)
    const { setCalcColumnState } = useActions(logic)

    const showCountedByTag = !!indexedResults.find(({ action }) => action?.math && action.math !== 'total')

    const handleEditClick = (item: IndexedTrendResult): void => {
        if (canEditSeriesNameInline) {
            const entityFitler = entityFilterLogic.findMounted({
                setFilters,
                filters,
                typeKey: filterKey,
            })
            if (entityFitler) {
                entityFitler.actions.selectFilter(item.action)
                entityFitler.actions.showModal()
            }
        }
    }

    const isDisplayModeNonTimeSeries: boolean =
        !!filters.display && NON_TIME_SERIES_DISPLAY_TYPES.includes(filters.display)

    const calcColumnMenu = isDisplayModeNonTimeSeries ? null : (
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
    const columns: LemonTableColumn<IndexedTrendResult, keyof IndexedTrendResult | undefined>[] = []

    if (isLegend) {
        columns.push({
            render: function RenderCheckbox(_, item: IndexedTrendResult) {
                return (
                    <LemonCheckbox
                        color={getSeriesColor(item.id, !!filters.compare)}
                        checked={!hiddenLegendKeys[item.id]}
                        onChange={() => toggleVisibility(item.id)}
                        disabled={!canCheckUncheckSeries}
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
                        seriesColor={getSeriesColor(item.id, !!filters.compare)}
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
                        <LemonButton
                            onClick={() => handleEditClick(item)}
                            title="Rename graph series"
                            icon={<IconEdit className="edit-icon" />}
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
                    <SeriesToggleWrapper
                        id={item.id}
                        toggleVisibility={isMainInsightView ? undefined : toggleVisibility}
                    >
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
        if (filters.display === ChartDisplayType.WorldMap) {
            columns.push({
                title: <PropertyKeyInfo disableIcon disablePopover value="$geoip_country_name" />,
                render: (_, item: IndexedTrendResult) => countryCodeToName[item.breakdown_value as string],
                key: 'breakdown_addendum',
                sorter: (a, b) => {
                    return countryCodeToName[a.breakdown_value as string].localeCompare(b.breakdown_value as string)
                },
            })
        }
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
                    return humanFriendlyNumber(item.data[index] ?? NaN)
                },
                key: `data-${index}`,
                sorter: (a, b) => (a.data[index] ?? NaN) - (b.data[index] ?? NaN),
                align: 'right',
            })
        )

        columns.push(...valueColumns)
    }

    if (showTotalCount) {
        columns.push({
            title: calcColumnMenu ? (
                <Dropdown overlay={calcColumnMenu}>
                    <span className="cursor-pointer">
                        {CALC_COLUMN_LABELS[calcColumnState]}
                        <DownOutlined className="ml-025" />
                    </span>
                </Dropdown>
            ) : (
                CALC_COLUMN_LABELS.total
            ),
            render: function RenderCalc(count: any, item: IndexedTrendResult) {
                if (calcColumnState === 'total' || isDisplayModeNonTimeSeries) {
                    return (item.count || item.aggregated_value || 'Unknown').toLocaleString()
                } else if (calcColumnState === 'average') {
                    return average(item.data).toLocaleString()
                } else if (calcColumnState === 'median') {
                    return median(item.data).toLocaleString()
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
            id={isViewedOnDashboard ? insight.short_id : undefined}
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
