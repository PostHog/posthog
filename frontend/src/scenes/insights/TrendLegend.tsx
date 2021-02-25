import React from 'react'
import { Table } from 'antd'
import { useActions, useValues } from 'kea'
import { IndexedTrendResult, trendsLogic } from 'scenes/trends/trendsLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'
import { MATHS } from 'lib/constants'

function formatLabel(item: IndexedTrendResult): string {
    const name = item.action?.name || item.label
    const math = item.action?.math
    const mathLabel = math ? MATHS[math].name : ''
    const propNum = item.action?.properties.length
    const propLabel = propNum ? propNum + (propNum === 1 ? ' property' : ' properties') : ''
    return name + (mathLabel ? ' — ' + mathLabel : '') + (propLabel ? ' — ' + propLabel : '')
}

export function TrendLegend(): JSX.Element {
    const { indexedResults, visibilityMap, filters } = useValues(trendsLogic)
    const { toggleVisibility } = useActions(trendsLogic)
    const isSingleEntity = indexedResults.length === 1

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
        {
            title: 'Label',
            render: function RenderLabel({}, item: IndexedTrendResult) {
                return (
                    <span
                        style={{ cursor: isSingleEntity ? undefined : 'pointer' }}
                        onClick={() => !isSingleEntity && toggleVisibility(item.id)}
                    >
                        {formatLabel(item)}
                    </span>
                )
            },
            fixed: 'left',
            width: 150,
        },
        ...(filters.breakdown
            ? [
                  {
                      title: 'Breakdown Value',
                      render: function RenderBreakdownValue({}, item: IndexedTrendResult) {
                          return item.breakdown_value === 'nan' ? 'Other' : item.breakdown_value
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
