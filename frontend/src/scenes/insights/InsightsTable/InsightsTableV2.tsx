import React from 'react'
import { Dropdown, Menu, Table, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { IndexedTrendResult, trendsLogic } from 'scenes/trends/trendsLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'
import { cohortsModel } from '~/models/cohortsModel'
import { CohortType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { average, median, maybeAddCommasToInteger } from 'lib/utils'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { CalcColumnState, insightsTableLogic } from './insightsTableLogic'
import { DownOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

interface InsightsTableProps {
    isLegend?: boolean // `true` -> Used as a supporting legend at the bottom of another graph; `false` -> used as it's own display
    showTotalCount?: boolean
}

const CALC_COLUMN_LABELS: Record<CalcColumnState, string> = {
    total: 'Total Sum',
    average: 'Average',
    median: 'Median',
}

export function InsightsTableV2({ isLegend = true, showTotalCount = false }: InsightsTableProps): JSX.Element | null {
    const { indexedResults, visibilityMap, filters, numberOfSeries } = useValues(trendsLogic)
    const { toggleVisibility } = useActions(trendsLogic)
    const { cohorts } = useValues(cohortsModel)
    const { reportInsightsTableCalcToggled } = useActions(eventUsageLogic)
    const hasUniqueFilter = !!(
        filters.actions?.find(({ math }) => math === 'dau') || filters.events?.find(({ math }) => math === 'dau')
    )
    const logic = insightsTableLogic({ hasUniqueFilter })
    const { calcColumnState } = useValues(logic)
    const { setCalcColumnState } = useActions(logic)

    if (indexedResults.length === 0 || !indexedResults?.[0]?.data) {
        return null
    }

    const isSingleEntity = indexedResults.length === 1
    const colorList = getChartColors('white')
    const showCountedByTag = !!indexedResults.find(({ action: { math } }) => math && math !== 'total')

    function SeriesToggleWrapper({ children, id }: { children: JSX.Element; id: number }): JSX.Element {
        return (
            <div
                style={{ cursor: isSingleEntity ? undefined : 'pointer' }}
                onClick={() => !isSingleEntity && toggleVisibility(id)}
            >
                {children}
            </div>
        )
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
            render: function RenderCheckbox({}, item: IndexedTrendResult, index: number) {
                // legend will always be on insight page where the background is white
                return (
                    <PHCheckbox
                        color={colorList[index]}
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
            title: <PropertyKeyInfo disableIcon disablePopover value={filters.breakdown || 'Breakdown Value'} />,
            render: function RenderBreakdownValue({}, item: IndexedTrendResult) {
                return (
                    <SeriesToggleWrapper id={item.id}>
                        <>{formatBreakdownLabel(item.breakdown_value, cohorts)}</>
                    </SeriesToggleWrapper>
                )
            },
            fixed: 'left',
            width: 150,
        })
    }

    if (!(numberOfSeries === 1 && indexedResults[0].breakdown_value)) {
        columns.push({
            title: 'Event or Action',
            render: function RenderLabel({}, item: IndexedTrendResult, index: number): JSX.Element {
                return (
                    <SeriesToggleWrapper id={item.id}>
                        <InsightLabel
                            seriesColor={colorList[index]}
                            action={item.action}
                            fallbackName={item.label}
                            hasMultipleSeries={indexedResults.length > 1}
                            showCountedByTag={showCountedByTag}
                            breakdownValue={item.breakdown_value?.toString()}
                            hideBreakdown
                            hideIcon
                        />
                    </SeriesToggleWrapper>
                )
            },
            fixed: 'left',
            width: 200,
        })
    }

    if (indexedResults && indexedResults.length > 0) {
        const valueColumns: ColumnsType<IndexedTrendResult> = indexedResults[0].data.map(({}, index: number) => ({
            title: indexedResults[0].labels[index],
            render: function RenderPeriod({}, item: IndexedTrendResult) {
                return maybeAddCommasToInteger(item.data[index])
            },
            align: 'center',
        }))

        columns.push(...valueColumns)
    }

    if (showTotalCount) {
        columns.push({
            title: (
                <Dropdown overlay={calcColumnMenu} trigger={['click']}>
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
                }
                return (
                    <>
                        {count.toLocaleString()}
                        {item.action.math === 'dau' && (
                            <Tooltip title="Keep in mind this is just the sum of all values in the row, not the unique users across the entire time period (i.e. this number may contain duplicate users).">
                                <InfoCircleOutlined style={{ marginLeft: 4, color: 'var(--primary-alt)' }} />
                            </Tooltip>
                        )}
                    </>
                )
            },
            dataIndex: 'count',
            fixed: 'right',
            width: 100,
            align: 'center',
        })
    }

    return (
        <Table
            dataSource={indexedResults}
            columns={columns}
            size="small"
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
            scroll={indexedResults && indexedResults.length > 0 ? { x: indexedResults[0].data.length * 160 } : {}}
            data-attr="insights-table-graph"
        />
    )
}

function formatBreakdownLabel(breakdown_value: string | number | undefined, cohorts: CohortType[]): string {
    if (breakdown_value && typeof breakdown_value == 'number') {
        return cohorts.filter((c) => c.id == breakdown_value)[0]?.name || breakdown_value.toString()
    } else if (typeof breakdown_value == 'string') {
        return breakdown_value === 'nan' ? 'Other' : breakdown_value
    } else {
        return ''
    }
}
