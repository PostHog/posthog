import { useValues } from 'kea'
import { LemonTable } from 'lib/components/LemonTable'
import React, { useEffect, useState } from 'react'
import { JSONTree } from 'react-json-tree'
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
                try {
                    const data = JSON.parse(result)
                    return (
                        <div style={{ minWidth: 300 }}>
                            <JSONTree
                                data={data}
                                shouldExpandNode={() => false}
                                theme={{
                                    scheme: 'bright',
                                    author: 'chris kempson (http://chriskempson.com)',
                                    base00: '#000000',
                                    base01: '#303030',
                                    base02: '#505050',
                                    base03: '#b0b0b0',
                                    base04: '#d0d0d0',
                                    base05: '#e0e0e0',
                                    base06: '#f5f5f5',
                                    base07: '#ffffff',
                                    base08: '#fb0120',
                                    base09: '#fc6d24',
                                    base0A: '#fda331',
                                    base0B: '#a1c659',
                                    base0C: '#76c7b7',
                                    base0D: '#6fb3d2',
                                    base0E: '#d381c3',
                                    base0F: '#be643c',
                                }}
                            />
                        </div>
                    )
                } catch {
                    return <div>{result}</div>
                }
            },
        }
    })

    return (
        <div>
            {columns.length ? (
                <LemonTable
                    columns={columns}
                    size="small"
                    rowKey="0"
                    dataSource={cleanedResult}
                    emptyState="This property value is an empty object."
                    pagination={{ pageSize: 100 }}
                />
            ) : null}
        </div>
    )
}
