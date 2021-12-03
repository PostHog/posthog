import React from 'react'
import { Dropdown, Menu, Skeleton, Table } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'
import { cohortsModel } from '~/models/cohortsModel'
import { BreakdownKeyType, CohortType, IntervalType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { average, median, maybeAddCommasToInteger } from 'lib/utils'
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

interface InsightsTableProps {
    isLegend?: boolean // `true` -> Used as a supporting legend at the bottom of another graph; `false` -> used as it's own display
    showTotalCount?: boolean
    filterKey: string // key for the entityFilterLogic
    canEditSeriesNameInline?: boolean
}

const CALC_COLUMN_LABELS: Record<CalcColumnState, string> = {
    total: 'Total Sum',
    average: 'Average',
    median: 'Median',
}

export function InsightsTable({
    isLegend = true,
    showTotalCount = false,
    filterKey,
    canEditSeriesNameInline,
}: InsightsTableProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { indexedResults, visibilityMap, filters, resultsLoading } = useValues(trendsLogic(insightProps))
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

    const isSingleEntity = indexedResults.length === 1
    const colorList = getChartColors('white')
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
                    onClick={() => {
                        setCalcColumnState(key as CalcColumnState)
                        reportInsightsTableCalcToggled(key)
                    }}
                >
                    {CALC_COLUMN_LABELS[key as CalcColumnState]}
                </Menu.Item>
            ))}
        </Menu>
    )

    // Build up columns to include. Order matters.
    const columns: ColumnsType<IndexedTrendResult> = []

    if (isLegend) {
        columns.push({
            title: '',
            render: function RenderCheckbox({}, item: IndexedTrendResult) {
                return (
                    <PHCheckbox
                        color={colorList[item.id]}
                        checked={visibilityMap[item.id]}
                        onChange={() => toggleVisibility(item.id)}
                        disabled={isSingleEntity}
                    />
                )
            },
            fixed: 'left',
            width: 30,
        })
    }

    if (filters.breakdown) {
        columns.push({
            title: (
                <PropertyKeyInfo disableIcon disablePopover value={filters.breakdown.toString() || 'Breakdown Value'} />
            ),
            render: function RenderBreakdownValue({}, item: IndexedTrendResult) {
                const label = formatBreakdownLabel(cohorts, item.breakdown_value)
                return (
                    <SeriesToggleWrapper id={item.id} toggleVisibility={toggleVisibility}>
                        <div title={label}>{label}</div>
                    </SeriesToggleWrapper>
                )
            },
            fixed: 'left',
            width: 150,
            sorter: (a, b) => {
                const labelA = formatBreakdownLabel(cohorts, a.breakdown_value)
                const labelB = formatBreakdownLabel(cohorts, b.breakdown_value)
                return labelA.localeCompare(labelB)
            },
        })
    }

    columns.push({
        title: 'Event or Action',
        render: function RenderLabel({}, item: IndexedTrendResult): JSX.Element {
            return (
                <div className="series-name-wrapper-col">
                    {canEditSeriesNameInline && (
                        <div className="edit-icon" onClick={() => handleEditClick(item)}>
                            <EditOutlined />
                        </div>
                    )}
                    <InsightLabel
                        seriesColor={colorList[item.id]}
                        action={item.action}
                        fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                        hasMultipleSeries={indexedResults.length > 1}
                        showCountedByTag={showCountedByTag}
                        breakdownValue={item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()}
                        hideBreakdown
                        hideIcon
                        useCustomName
                        className={clsx({
                            editable: canEditSeriesNameInline,
                        })}
                        hideSeriesSubtitle
                        onLabelClick={canEditSeriesNameInline ? () => handleEditClick(item) : undefined}
                    />
                </div>
            )
        },
        fixed: 'left',
        width: 200,
        sorter: (a, b) => {
            const labelA = a.action?.name || a.label || ''
            const labelB = b.action?.name || b.label || ''
            return labelA.localeCompare(labelB)
        },
    })

    if (indexedResults?.length > 0 && indexedResults[0].data) {
        const valueColumns: ColumnsType<IndexedTrendResult> = indexedResults[0].data.map(({}, index: number) => ({
            title: (
                <DateDisplay
                    interval={(filters.interval as IntervalType) || 'day'}
                    date={(indexedResults[0].dates || indexedResults[0].days)[index]}
                    hideWeekRange
                />
            ),
            render: function RenderPeriod({}, item: IndexedTrendResult) {
                return maybeAddCommasToInteger(item.data[index])
            },
            sorter: (a, b) => a.data[index] - b.data[index],
            align: 'center',
        }))

        columns.push(...valueColumns)
    }

    if (showTotalCount) {
        columns.push({
            title: (
                <Dropdown overlay={calcColumnMenu}>
                    <span className="cursor-pointer">
                        {CALC_COLUMN_LABELS[calcColumnState]} <DownOutlined />
                    </span>
                </Dropdown>
            ),
            render: function RenderCalc(count: number, item: IndexedTrendResult) {
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
                        {count.toLocaleString()}
                        {item.action && item.action?.math === 'dau' && (
                            <Tooltip title="Keep in mind this is just the sum of all values in the row, not the unique users across the entire time period (i.e. this number may contain duplicate users).">
                                <InfoCircleOutlined style={{ marginLeft: 4, color: 'var(--primary-alt)' }} />
                            </Tooltip>
                        )}
                    </>
                )
            },
            defaultSortOrder: 'descend',
            sorter: (a, b) => (a.count || a.aggregated_value) - (b.count || b.aggregated_value),
            dataIndex: 'count',
            fixed: 'right',
            width: 120,
            align: 'center',
        })
    }

    if (resultsLoading) {
        return <Skeleton active paragraph={{ rows: 4 }} />
    }

    return (
        <Table
            dataSource={indexedResults}
            columns={columns}
            size="small"
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
            scroll={
                indexedResults && indexedResults.length > 0 && indexedResults[0].data
                    ? { x: indexedResults[0].data.length * 160 }
                    : {}
            }
            data-attr="insights-table-graph"
        />
    )
}

export function formatBreakdownLabel(cohorts: CohortType[], breakdown_value?: BreakdownKeyType): string {
    if (breakdown_value && typeof breakdown_value == 'number') {
        return cohorts.filter((c) => c.id == breakdown_value)[0]?.name || breakdown_value.toString()
    } else if (typeof breakdown_value == 'string') {
        return breakdown_value === 'nan' ? 'Other' : breakdown_value === '' ? 'None' : breakdown_value
    } else if (Array.isArray(breakdown_value)) {
        return breakdown_value.join('::')
    } else {
        return ''
    }
}
