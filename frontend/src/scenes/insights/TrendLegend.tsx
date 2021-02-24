import React from 'react'
import { Table } from 'antd'
import { useActions, useValues } from 'kea'
import { IndexedTrendResult, trendsLogic } from 'scenes/trends/trendsLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'

export function TrendLegend(): JSX.Element {
    const { indexedResults, visibilityMap, filters } = useValues(trendsLogic)
    const { toggleVisibility } = useActions(trendsLogic)

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
                    />
                )
            },
            fixed: 'left',
            width: 60,
        },
        {
            title: 'Label',
            render: function RenderLabel({}, item: IndexedTrendResult) {
                return item.action?.name || item.label
            },
            fixed: 'left',
            width: 150,
        },
        ...(filters.breakdown
            ? [
                  {
                      title: 'Breakdown Value',
                      render: function RenderBreakdownValue({}, item: IndexedTrendResult) {
                          return item.breakdown_value
                      },
                      fixed: 'left',
                      width: 150,
                  },
              ]
            : []),
        ...(indexedResults && indexedResults.length > 0
            ? indexedResults[0].data.map(({}, index: number) => ({
                  title: indexedResults[0].labels[index],
                  render: function RenderPeriod({}, item: IndexedTrendResult) {
                      return item.data[index]
                  },
              }))
            : []),
    ]

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
