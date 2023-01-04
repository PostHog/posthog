import { actions, kea, key, props, reducers, selectors, path } from 'kea'
import {
    TimeToSeeInteractionNode,
    TimeToSeeNode,
    TimeToSeeQueryNode,
    TimeToSeeSessionNode,
} from '~/queries/nodes/TimeToSeeData/types'
import { dayjs } from 'lib/dayjs'

import type { traceLogicType } from './traceLogicType'

export interface SpanData {
    id: string // not provided by backend
    type: 'session' | 'interaction' | 'event' | 'query' | 'subquery'
    start: number // milliseconds after session start
    duration: number
    data: TimeToSeeNode
    depth?: number
    children: SpanData[]
}

export interface TraceLogicProps {
    sessionNode: TimeToSeeSessionNode
}

export function getDurationMs(node: TimeToSeeNode): number {
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

function walkSpans(
    nodes: Array<TimeToSeeInteractionNode | TimeToSeeQueryNode>,
    sessionStart: dayjs.Dayjs,
    level: number = 1
): SpanData[] {
    const spanData: SpanData[] = []

    nodes.forEach((node, index) => {
        const walkedChildren = walkSpans(node.children, sessionStart, level++)

        const start = dayjs(node.data.timestamp).diff(sessionStart)
        const duration = getDurationMs(node)
        spanData.push({
            id: `${node.type}-${level}-${index}`,
            type: node.type,
            start: start,
            duration: duration,
            data: node,
            depth: level,
            children: walkedChildren,
        })
    })

    return spanData
}

function flattenSpans(timeToSeeSession: TimeToSeeSessionNode): SpanData[] {
    const walkedChildren = walkSpans(timeToSeeSession.children, dayjs(timeToSeeSession.data.session_start))
    walkedChildren.unshift({
        id: timeToSeeSession.data.session_id,
        type: 'session',
        start: 0,
        duration: getDurationMs(timeToSeeSession),
        data: timeToSeeSession,
        children: [], // the session's children are shown separately
    })

    return walkedChildren
}

export const traceLogic = kea<traceLogicType>([
    path(['queries', 'nodes', 'TimeToSeeData', 'Trace', 'traceLogic']),
    props({} as TraceLogicProps),
    key((props) => props?.sessionNode?.data.session_id || 'pre-init'),
    actions({
        showInteractionTrace: (spanData: SpanData | null) => ({
            spanData,
        }),
    }),
    reducers({
        focussedInteraction: [
            null as SpanData | null,
            {
                showInteractionTrace: (_, { spanData }) => (!!spanData ? { ...spanData } : null),
            },
        ],
    }),
    selectors(() => ({
        processedSpans: [() => [(_, props) => props.sessionNode], (sessionNode) => flattenSpans(sessionNode)],
    })),
])
