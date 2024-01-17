import { kea, key, path, props, selectors } from 'kea'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { humanFriendlyMilliseconds } from 'lib/utils'

import {
    isSessionNode,
    TimeToSeeInteractionNode,
    TimeToSeeNode,
    TimeToSeeQueryNode,
    TimeToSeeSessionNode,
} from '../types'
import type { traceLogicType } from './traceLogicType'

export interface TraceLogicProps {
    sessionNode: TimeToSeeSessionNode
}

export function sessionNodeFacts(node: TimeToSeeNode): Record<string, JSX.Element | string | number> {
    return isSessionNode(node)
        ? {
              type: 'session',
              session_id: node.data.session_id,
              user: <ProfilePicture user={node.data.user} showName size="sm" />,
              duration: humanFriendlyMilliseconds(node.data.duration_ms) || 'unknown',
              sessionEventCount: node.data.events_count,
              frustratingInteractions: node.data.frustrating_interactions_count,
          }
        : {}
}

export interface SpanData {
    id: string // not provided by backend
    type: 'session' | 'interaction' | 'event' | 'query' | 'subquery'
    start: number // milliseconds after session start
    duration: number
    data: TimeToSeeNode
    depth?: number
    children: SpanData[]
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
    selectors(() => ({
        processedSpans: [(_, p) => [p.sessionNode], (sessionNode) => flattenSpans(sessionNode)],
        maxTimePoint: [
            (selectors) => [selectors.processedSpans],
            (processedSpans) => {
                // the session span duration isn't always the longest value even though it _should_ be
                // for now make the display make sense and then we can fix the data / parse it more correctly
                let max = 0
                for (const span of processedSpans) {
                    max = Math.max(max, span.start + span.duration)
                }
                return max
            },
        ],
    })),
])
