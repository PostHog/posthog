import { useValues } from 'kea'
import { LemonTable } from 'lib/components/LemonTable'
import React from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

export function UserSQLInsight(): JSX.Element {
    const { insight } = useValues(insightLogic)

    const keys = Object.keys(insight?.result?.[0] || [])

    const columns = keys.map((key) => {
        return {
            title: key,
            dataIndex: key,
            render: function RenderKey(result): JSX.Element {
                return <div>{result}</div>
            },
        }
    })

    return (
        <LemonTable
            columns={columns}
            // showHeader={!embedded}
            size="small"
            rowKey="0"
            // embedded={embedded}
            dataSource={insight.result}
            // className={className}
            emptyState="This property value is an empty object."
        />
    )
}
