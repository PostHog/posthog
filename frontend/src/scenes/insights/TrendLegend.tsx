import React from 'react'
import { Table } from 'antd'
import { useActions, useValues } from 'kea'
import { trendsLogic } from './trendsLogic'
import { ViewType } from './insightLogic'

interface Props {
    view: ViewType
}

export function TrendLegend({ view }: Props): JSX.Element {
    const { indexedResults, selectedIds } = useValues(trendsLogic({ dashboardItemId: null, view }))
    const { toggleVisibility } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const columns = [
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
            rowSelection={{
                type: 'checkbox',
                selectedRowKeys: selectedIds,
                onSelect: (record) => toggleVisibility(record.id),
            }}
        />
    )
}
