import React from 'react'
import { Table } from 'antd'
import { useActions, useValues } from 'kea'
import { trendsLogic } from './trendsLogic'
import { ViewType } from './insightLogic'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { getChartColors } from 'lib/colors'

interface Props {
    view: ViewType
}

export function TrendLegend({ view }: Props): JSX.Element {
    const { indexedResults, visibilityMap, filters } = useValues(trendsLogic({ dashboardItemId: null, view }))
    const { toggleVisibility } = useActions(trendsLogic({ dashboardItemId: null, view }))

    const columns = [
        {
            title: '',
            render: function RenderChckbox({}, item, index: number) {
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
            render: function RenderLabel({}, item) {
                return item.action.name
            },
            fixed: 'left',
            width: 150,
        },
        ...(filters.breakdown
            ? [
                  {
                      title: 'Breakdown Value',
                      render: function RenderBreakdownValue({}, item) {
                          return item.breakdown_value
                      },
                      fixed: 'left',
                      width: 150,
                  },
              ]
            : []),
        ...(indexedResults && indexedResults.length > 0
            ? indexedResults[0].data.map(({}, index) => ({
                  title: indexedResults[0].labels[index],
                  render: function RenderPeriod({}, item) {
                      return item.data[index]
                  },
              }))
            : []),
    ]

    return (
        <Table
            dataSource={indexedResults}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
            scroll={indexedResults && indexedResults.length > 0 ? { x: indexedResults[0].data.length * 160 } : {}}
        />
    )
}
