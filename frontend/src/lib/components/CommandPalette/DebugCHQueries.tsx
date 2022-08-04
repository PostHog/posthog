import React, { useState } from 'react'
import { Modal } from 'antd'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from '../LemonButton'
import { LemonTable } from '../LemonTable'

interface Query {
    timestamp: number
    query: string
    exception: string
    type: number
    execution_time: number
    path: string
}

function nthChar(string: string, character: string, n: number): number {
    let count = 0,
        i = 0
    while (count < n && (i = string.indexOf(character, i) + 1)) {
        count++
    }
    if (count == n) {return i - 1}
    return -1
}

function QueryCol({ item }: { item: query }): JSX.Element {
    const [expanded, setExpanded] = useState(false as boolean)

    const has5lines = nthChar(item.query, '\n', 5)
    if (has5lines === -1) {
        return (
            <pre className="code" style={{ maxWidth: 600, fontSize: 10, padding: 10 }}>
                {item.query}
            </pre>
        )
    }
    return (
        <>
            <pre className="code" style={{ maxWidth: 600, fontSize: 10, padding: 10 }}>
                {expanded ? item.query : item.query.slice(0, has5lines)}
            </pre>
            <LemonButton size="small" onClick={() => setExpanded(!expanded)}>
                {expanded ? 'Show less' : 'Show more'}
            </LemonButton>
        </>
    )
}

function ModalContent({ origResult }: { origResult: Query[] }): JSX.Element {
    const [pathFilter, setPathFilter] = useState(null as string | null)

    const paths = Object.entries(
        origResult
            .map((result) => result.path)
            .reduce((acc, val) => {
                acc[val] = acc[val] === undefined ? 1 : (acc[val] += 1)
                return acc
            }, {})
    ).sort((a: any, b: any) => b[1] - a[1])

    const results = pathFilter ? origResult.filter((item) => item.path === pathFilter) : origResult

    return (
        <>
            {paths.map(([path, count]) => (
                <LemonButton
                    key={path}
                    type={pathFilter === path ? 'primary' : 'default'}
                    size="small"
                    onClick={() => (pathFilter === path ? setPathFilter(null) : setPathFilter(path))}
                >
                    {path} ({count})
                </LemonButton>
            ))}
            {pathFilter && <LemonButton onClick={() => setPathFilter(null)}>Remove path filter</LemonButton>}

            <LemonTable
                columns={[
                    { title: 'Timestamp', render: (_, item) => dayjs(item.timestamp).format() },
                    {
                        title: 'Query',
                        render: function query(_, item) {
                            return (
                                <>
                                    {item.exception}
                                    <QueryCol item={item} />
                                </>
                            )
                        },
                    },
                    {
                        title: 'Execution duration (seconds)',
                        render: function exec(_, item) {
                            return <>{Math.round((item.execution_time + Number.EPSILON) * 100) / 100}</>
                        },
                    },
                ]}
                dataSource={results}
                size="small"
                pagination={undefined}
            />
        </>
    )
}

export async function debugCHQueries(): Promise<void> {
    const results = await api.get('api/debug_ch_queries/')

    Modal.info({
        visible: true,
        width: '80%',
        title: 'ClickHouse queries recently executed for this user',
        icon: null,
        content: <ModalContent origResult={results} />,
    })
    setTimeout(() => document?.querySelector('.ant-modal-wrap')?.scrollTo(0, 0), 200)
}
