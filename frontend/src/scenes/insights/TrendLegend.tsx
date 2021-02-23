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
    const { indexedResults, visibilityMap } = useValues(trendsLogic({ dashboardItemId: null, view }))
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
        },
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
        },
        {
            title: 'Label',
            dataIndex: 'label',
            key: 'label',
        },
    ]

    return (
        <Table
            dataSource={indexedResults}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
        />
    )
}
