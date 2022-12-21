import MonacoEditor from '@monaco-editor/react'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { TimeToSeeDataQuery } from '~/queries/schema'
import { useValues } from 'kea'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { timeToSeeDataLogic } from './timeToSeeDataLogic'
import { TimeToSeeNode } from './types'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'


let uniqueNode = 0

/** Default renderer for data nodes. Display the JSON in a Monaco editor.  */
export function TimeToSeeData(props: { query: TimeToSeeDataQuery }): JSX.Element {
    const [key] = useState(() => `TimeToSeeData.${uniqueNode++}`)
    const logic = timeToSeeDataLogic({ query: props.query, key })
    const { response, responseLoading } = useValues(logic)

    if (responseLoading) {
        return (
            <div className="text-2xl">
                <Spinner />
            </div>
        )
    }

    if (!response) {
        return (
            <div className="text-2xl">
                No session found.
            </div>
        )
    }

    const columns: LemonTableColumns<TimeToSeeNode> = [
        {
            title: 'Type',
            dataIndex: 'type'
        },
        {
            title: 'Page',
            render: (_, node) => {
                return (node.type == 'event' || node.type == 'interaction') && node.data.current_url
            }
        },
        {
            title: 'Duration',
            render: (_, node) => {
                const duration = getDurationMs(node)
                return `${duration}ms`
            }
        }
    ]

    return (
        <>
            <LemonTable
                dataSource={response.children}
                columns={columns}
                expandable={{
                    expandedRowRender: (node) => (<RenderRow depth={0} node={node} />)
                }}
            />

            <AutoSizer disableWidth>
                {({ height }) => (
                    <MonacoEditor
                        theme="vs-light"
                        className="border"
                        language={'json'}
                        value={JSON.stringify(response, null, 2)}
                        height={Math.max(height, 300)}
                    />
                )}
            </AutoSizer>
        </>
    )
}

function RenderRow(props: { depth: number, node: TimeToSeeNode }) {
    return (
        <>
            <div className="">
                <div>
                    <strong>{props.node.type}</strong>
                </div>
                <div>
                    {getDurationMs(props.node)}ms
                </div>
            </div>
            {props.node.children.map((childNode, index) => <RenderRow depth={props.depth + 1} node={childNode} key={index}/>)}
        </>
    )
}

function getDurationMs(node: TimeToSeeNode): number {
    switch (node.type) {
        case 'session':
            return node.data.duration_ms
        case 'interaction':
        case 'event':
            return node.data.time_to_see_data_ms
        case 'query':
        case 'subquery':
            return node.data.query_duration_ms
    }
}
