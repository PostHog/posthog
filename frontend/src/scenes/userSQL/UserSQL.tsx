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

    const isResultSingle = (): boolean => {
        return insight?.result?.length === 1 && Object.keys(insight.result[0]).length === 1
    }

    const getSingleResult = (result): number => {
        return Object.values(result[0])[0] as number
    }

    return isResultSingle() ? (
        <div
            style={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                margin: 30,
                fontSize: 55,
                fontWeight: 'bold',
            }}
        >
            {getSingleResult(insight.result)}
        </div>
    ) : (
        <LemonTable
            columns={columns}
            size="small"
            rowKey="0"
            dataSource={insight.result}
            emptyState="This property value is an empty object."
        />
    )
}
