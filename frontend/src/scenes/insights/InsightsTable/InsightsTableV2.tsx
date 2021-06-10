import React from 'react'
import { Table } from 'antd'
import { useActions, useValues } from 'kea'
import { IndexedTrendResult, trendsLogic } from 'scenes/trends/trendsLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'
import { cohortsModel } from '~/models/cohortsModel'
import { CohortType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { maybeAddCommasToInteger } from 'lib/utils'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

function formatBreakdownLabel(breakdown_value: string | number | undefined, cohorts: CohortType[]): string {
    if (breakdown_value && typeof breakdown_value == 'number') {
        return cohorts.filter((c) => c.id == breakdown_value)[0]?.name || breakdown_value.toString()
    } else if (typeof breakdown_value == 'string') {
        return breakdown_value === 'nan' ? 'Other' : breakdown_value
    } else {
        return ''
    }
}

interface InsightsTableProps {
    isLegend?: boolean // `true` -> Used as a supporting legend at the bottom of another graph; `false` -> used as it's own display
    showTotalCount?: boolean
}

export function InsightsTableV2({ isLegend = true, showTotalCount = false }: InsightsTableProps): JSX.Element | null {
    const { indexedResults, visibilityMap, filters, numberOfSeries } = useValues(trendsLogic)
    const { toggleVisibility } = useActions(trendsLogic)
    const { cohorts } = useValues(cohortsModel)
    const isSingleEntity = indexedResults.length === 1

    if (indexedResults.length === 0 || !indexedResults?.[0]?.data) {
        return null
    }

    const colorList = getChartColors('white')
    const showCountedByTag = !!indexedResults.find(({ action: { math } }) => math && math !== 'total')

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
                return formatBreakdownLabel(item.breakdown_value, cohorts)
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
                    <div
                        style={{ cursor: isSingleEntity ? undefined : 'pointer' }}
                        onClick={() => !isSingleEntity && toggleVisibility(item.id)}
                    >
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
                    </div>
                )
            },
            fixed: 'left',
            width: 200,
        })
    }

    if (indexedResults && indexedResults.length > 0) {
        const valueColumns = indexedResults[0].data.map(({}, index: number) => ({
            title: indexedResults[0].labels[index],
            render: function RenderPeriod({}, item: IndexedTrendResult) {
                return maybeAddCommasToInteger(item.data[index])
            },
        }))

        columns.push(...valueColumns)
    }

    if (showTotalCount) {
        columns.push({
            title: 'Total',
            dataIndex: 'count',
            fixed: 'right',
            width: 100,
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
