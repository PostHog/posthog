import { useValues } from 'kea'
import { LemonTable } from 'lib/components/LemonTable'
import React, { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

function convertArrayToString(payload): any {
    if (!payload) {
        return []
    }

    return payload.map((item) => {
        const newItem = {}
        Object.keys(item).map((key) => {
            if (Array.isArray(item[key])) {
                newItem[key] = JSON.stringify(item[key])
            } else {
                newItem[key] = item[key]
            }
        })
        return newItem
    })
}

export function UserSQLInsight(): JSX.Element {
    const { insight } = useValues(insightLogic)
    const [cleanedResult, setResult] = useState(convertArrayToString(insight.result))

    useEffect(() => {
        setResult(convertArrayToString(insight.result))
    }, [insight.result])

    const keys = Object.keys(cleanedResult?.[0] || [])

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
        return cleanedResult?.length === 1 && Object.keys(cleanedResult[0]).length === 1
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
            {getSingleResult(cleanedResult)}
        </div>
    ) : (
        <LemonTable
            columns={columns}
            size="small"
            rowKey="0"
            dataSource={cleanedResult}
            emptyState="This property value is an empty object."
        />
    )
}
