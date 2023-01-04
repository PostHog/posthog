import MonacoEditor from '@monaco-editor/react'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { TimeToSeeDataQuery } from '~/queries/schema'
import { useValues } from 'kea'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { timeToSeeDataLogic } from './timeToSeeDataLogic'
import { TimeToSeeNode } from './types'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { dayjs } from 'lib/dayjs'

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
        return <div className="text-2xl">No session found.</div>
    }

    const columns: LemonTableColumns<TimeToSeeNode> = [
        {
            title: 'Type',
            dataIndex: 'type',
            render: (_, node) => {
                if (node.type == 'event' || node.type == 'interaction') {
                    return `${node.data.action ?? 'load'} in ${node.data.context}`
                }
                return 'ClickHouse query'
            },
        },
        {
            title: 'Context',
            render: (_, node) => {
                if (node.type == 'event' || node.type == 'interaction') {
                    return node.data.context
                }
            },
        },
        {
            title: 'Action',
            render: (_, node) => {
                if (node.type == 'event' || node.type == 'interaction') {
                    return node.data.action
                }
            },
        },
        {
            title: 'Page',
            render: (_, node) => {
                return (node.type == 'event' || node.type == 'interaction') && node.data.current_url
            },
        },
        {
            title: 'Cache hit ratio',
            render: (_, node) => {
                if (node.type == 'event' || node.type == 'interaction') {
                    const ratio = node.data.insights_fetched_cached / node.data.insights_fetched
                    return `${Math.round(ratio * 100)}%`
                }
            },
        },
        {
            title: 'Duration',
            render: (_, node) => {
                const duration = getDurationMs(node)
                return `${duration}ms`
            },
        },
    ]

    return (
        <>
            <LemonTable
                dataSource={response.children}
                columns={columns}
                expandable={{
                    expandedRowRender: (node) => <RenderHierarchy depth={0} node={node} rootNode={node} />,
                    isRowExpanded: () => true,
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

function RenderHierarchy(props: { depth: number; node: TimeToSeeNode; rootNode: TimeToSeeNode }): JSX.Element {
    const [startWidth, durationWidth] = getTimeSlice(props.node, props.rootNode)
    return (
        <>
            <div className="flex">
                <div className="flex">
                    <span
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: props.depth * 100 }}
                    />
                    <strong>{props.node.type}</strong>
                </div>
                <div
                    className="flex"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: 400 }}
                >
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${startWidth * 100}%` }}
                    />
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${durationWidth * 100}%`, height: 10, backgroundColor: 'red' }}
                    />
                </div>
                <div>{getDurationMs(props.node)}ms</div>
            </div>
            {props.node.children.map((childNode, index) => (
                <RenderHierarchy {...props} depth={props.depth + 1} node={childNode} key={index} />
            ))}
        </>
    )
}

function getTimeSlice(node: TimeToSeeNode, rootNode: TimeToSeeNode): [number, number] {
    const rootDuration = getDurationMs(rootNode)
    const duration = getDurationMs(node)
    const rootEndTime = getEndTime(rootNode)
    const endTime = getEndTime(node)

    const startDiffMs = rootEndTime.diff(endTime, 'milliseconds')

    return [startDiffMs / rootDuration, duration / rootDuration]
}

function getEndTime(node: TimeToSeeNode): dayjs.Dayjs {
    switch (node.type) {
        case 'session':
            return dayjs(node.data.session_start)
        case 'interaction':
        case 'event':
        case 'query':
        case 'subquery':
            return dayjs(node.data.timestamp)
    }
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
