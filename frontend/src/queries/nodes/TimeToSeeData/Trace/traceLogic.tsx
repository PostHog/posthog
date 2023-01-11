import { actions, kea, key, props, reducers, selectors, path } from 'kea'
import {
    isInteractionNode,
    isQueryNode,
    isSessionNode,
    TimeToSeeInteractionNode,
    TimeToSeeNode,
    TimeToSeeQueryNode,
    TimeToSeeSessionNode,
} from '~/queries/nodes/TimeToSeeData/types'
import { dayjs } from 'lib/dayjs'

import type { traceLogicType } from './traceLogicType'
import { humanFriendlyMilliseconds, humanizeBytes } from 'lib/utils'
import { ProfilePicture } from 'lib/components/ProfilePicture'

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

function interactionNodeFacts(node: TimeToSeeNode): Record<string, JSX.Element | string | number> {
    return isInteractionNode(node)
        ? {
              type: `${node.data.action || 'load'} in ${node.data.context}`,
              context: node.data.context,
              action: node.data.action,
              page: node.data.current_url,
              cacheHitRatio: `${Math.round((node.data.insights_fetched_cached / node.data.insights_fetched) * 100)}%`,
              responseBytes: humanizeBytes(node.data.api_response_bytes),
              isFrustrating: !!node.data.is_frustrating ? 'true' : 'false',
              status: node.data.status,
          }
        : {}
}

export function sessionNodeFacts(node: TimeToSeeNode): Record<string, JSX.Element | string | number> {
    return isSessionNode(node)
        ? {
              type: 'session',
              session_id: node.data.session_id,
              user: <ProfilePicture name={node.data.user.first_name} email={node.data.user.email} showName size="sm" />,
              duration: humanFriendlyMilliseconds(node.data.duration_ms) || 'unknown',
              sessionEventCount: node.data.events_count,
              frustratingInteractions: node.data.frustrating_interactions_count,
          }
        : {}
}

function queryNodeFacts(node: TimeToSeeNode): Record<string, JSX.Element | string | number> {
    return isQueryNode(node)
        ? {
              type: `Clickhouse: ${node.data.query_type}`,
              hasJoins: !!node.data.has_joins ? 'true' : 'false',
              queryDuration: humanFriendlyMilliseconds(node.data.query_duration_ms) || 'unknown',
          }
        : {}
}

function nodeFacts(node: TimeToSeeNode): Record<string, any> {
    if (isSessionNode(node)) {
        return sessionNodeFacts(node)
    } else if (isInteractionNode(node)) {
        return interactionNodeFacts(node)
    } else if (isQueryNode(node)) {
        return queryNodeFacts(node)
    }
    throw new Error('unknown node, cannot generate facts')
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
        showNode: (spanData: SpanData | null) => ({ spanData }),
    }),
    reducers({
        focussedInteraction: [
            null as SpanData | null,
            {
                showInteractionTrace: (_, { spanData }) => (!!spanData ? { ...spanData } : null),
            },
        ],
        focussedNode: [
            null as SpanData | null,
            {
                showNode: (_, { spanData }) => (!!spanData ? { ...spanData } : null),
                showInteractionTrace: (_, { spanData }) => (!!spanData ? { ...spanData } : null),
            },
        ],
    }),
    selectors(() => ({
        focussedInteractionStartTime: [
            (s) => [s.focussedInteraction],
            (focussedInteraction) => focussedInteraction?.start || null,
        ],
        processedSpans: [() => [(_, props) => props.sessionNode], (sessionNode) => flattenSpans(sessionNode)],
        currentFacts: [(s) => [s.focussedNode], (focussedNode) => (focussedNode ? nodeFacts(focussedNode.data) : null)],
    })),
])
