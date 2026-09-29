import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EnrichedTraceTreeNode } from '../../../aiObservabilityTraceDataLogic'
import { aiTokenCount, formatLLMEventTitle, getLLMEventKind } from '../../../utils'
import { toDisplayText } from '../components/jsonText'
import { NodeStats, TraceTreeNode } from '../types'
import { readString } from './propertyReaders'

export function isErrorEvent(event: LLMTraceEvent): boolean {
    const isErrorFlag = event.properties.$ai_is_error
    return !!event.properties.$ai_error || isErrorFlag === true || isErrorFlag === 'true'
}

export function eventError(event: LLMTraceEvent): string | null {
    return isErrorEvent(event) ? toDisplayText(event.properties.$ai_error ?? 'This step failed.') : null
}

export function hasTraceError(trace: LLMTrace): boolean {
    return (trace.errorCount ?? 0) > 0
}

export function traceStats(trace: LLMTrace): NodeStats {
    return {
        costUsd: trace.totalCost ?? null,
        inputTokens: trace.inputTokens ?? null,
        outputTokens: trace.outputTokens ?? null,
        cacheReadTokens: null,
        latencyMs: trace.totalLatency !== undefined ? trace.totalLatency * 1000 : null,
    }
}

function nodeStats(node: EnrichedTraceTreeNode): NodeStats {
    const properties = node.event.properties
    return {
        costUsd: node.displayTotalCost,
        inputTokens: node.aggregation
            ? node.aggregation.inputTokens || null
            : aiTokenCount(properties.$ai_input_tokens),
        outputTokens: node.aggregation
            ? node.aggregation.outputTokens || null
            : aiTokenCount(properties.$ai_output_tokens),
        cacheReadTokens: aiTokenCount(properties.$ai_cache_read_input_tokens),
        latencyMs: node.displayLatency > 0 ? node.displayLatency * 1000 : null,
    }
}

function toNode(node: EnrichedTraceTreeNode): TraceTreeNode {
    return {
        id: node.event.id,
        kind: getLLMEventKind(node.event),
        name: formatLLMEventTitle(node.event),
        model: readString(node.event.properties.$ai_model),
        stats: nodeStats(node),
        hasError: isErrorEvent(node.event),
        children: (node.children ?? []).map(toNode),
    }
}

export function toTraceTree(trace: LLMTrace, enrichedTree: EnrichedTraceTreeNode[]): TraceTreeNode[] {
    return [
        {
            id: trace.id,
            kind: 'trace',
            name: formatLLMEventTitle(trace),
            model: null,
            stats: traceStats(trace),
            hasError: hasTraceError(trace),
            children: enrichedTree.map(toNode),
        },
    ]
}

export function findTreeNode(nodes: TraceTreeNode[], id: string): TraceTreeNode | null {
    for (const node of nodes) {
        if (node.id === id) {
            return node
        }
        const found = findTreeNode(node.children, id)
        if (found) {
            return found
        }
    }
    return null
}

export function preOrderIds(nodes: TraceTreeNode[]): string[] {
    return nodes.flatMap((node) => [node.id, ...preOrderIds(node.children)])
}
