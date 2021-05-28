import React from 'react'
import { Table } from 'antd'
import { useActions, useValues } from 'kea'
import { IndexedTrendResult, trendsLogic } from 'scenes/trends/trendsLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'
import { cohortsModel } from '~/models'
import { CohortType } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { alphabet, maybeAddCommasToInteger } from 'lib/utils'
import InsightsLabel from 'lib/components/InsightsLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import SeriesBadge from 'lib/components/SeriesBadge'

interface FormatLabelProps {
    item: IndexedTrendResult
    index: number
    showSeriesIndex?: boolean
    showCountedByTag?: boolean
}

function SeriesLabel({ item, index, showSeriesIndex, showCountedByTag }: FormatLabelProps): JSX.Element {
    const seriesColor = getChartColors('white')[index]
    return (
        <div style={{ display: 'flex', alignItems: 'center' }}>
            {showSeriesIndex && alphabet[index] && <SeriesBadge color={seriesColor}>{alphabet[index]}</SeriesBadge>}
            <InsightsLabel
                propertyValue={item.action?.name || item.label}
                action={item.action}
                showCountedByTag={showCountedByTag}
            />
        </div>
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

export function TrendLegend(): JSX.Element | null {
    const { indexedResults, visibilityMap, filters } = useValues(trendsLogic)
    const { toggleVisibility } = useActions(trendsLogic)
    const { cohorts } = useValues(cohortsModel)
    const isSingleEntity = indexedResults.length === 1

    if (indexedResults.length === 0) {
        return null
    }
    const showCountedByTag = !!indexedResults.find(({ action: { math } }) => math && math !== 'total')

    const columns = [
        {
            title: '',
            render: function RenderCheckbox({}, item: IndexedTrendResult, index: number) {
                // legend will always be on insight page where the background is white
                return (
                    <PHCheckbox
                        color={getChartColors('white')[index]}
                        checked={visibilityMap[item.id]}
                        onChange={() => toggleVisibility(item.id)}
                        disabled={isSingleEntity}
                    />
                )
            },
            fixed: 'left',
            width: 60,
        },
        filters.breakdown
            ? {
                  title: <PropertyKeyInfo disableIcon value={filters.breakdown || 'Breakdown Value'} />,
                  render: function RenderBreakdownValue({}, item: IndexedTrendResult) {
                      return formatBreakdownLabel(item.breakdown_value, cohorts)
                  },
                  fixed: 'left',
                  width: 150,
              }
            : null,
        {
            title: 'Event/Action',
            render: function RenderLabel({}, item: IndexedTrendResult, index: number) {
                return (
                    <span
                        style={{ cursor: isSingleEntity ? undefined : 'pointer' }}
                        onClick={() => !isSingleEntity && toggleVisibility(item.id)}
                    >
                        <SeriesLabel
                            index={index}
                            item={item}
                            showCountedByTag={showCountedByTag}
                            showSeriesIndex={indexedResults.length > 1}
                        />
                    </span>
                )
            },
            fixed: 'left',
            width: 150,
        },
    ].filter(Boolean) as ColumnsType<IndexedTrendResult>

    if (indexedResults && indexedResults.length > 0) {
        const valueColumns = indexedResults[0].data.map(({}, index: number) => ({
            title: indexedResults[0].labels[index],
            render: function RenderPeriod({}, item: IndexedTrendResult) {
                return maybeAddCommasToInteger(item.data[index])
            },
        }))

        columns.push(...valueColumns)
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
        />
    )
}
