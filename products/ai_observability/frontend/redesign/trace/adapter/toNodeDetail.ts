import type { TraceEvaluationResultApi, TraceNodeApi } from '../../../generated/api.schemas'
import { NodeDetailProps } from '../components/NodeDetail'
import { EvalsState, LoadFailure, NodeContent, NodeLoad, NodeProperties } from '../types'
import { toEvalResults } from './toEvalResults'

export type NodeDetailData = Omit<
    NodeDetailProps,
    | 'tab'
    | 'raw'
    | 'onTabChange'
    | 'onViewInThread'
    | 'messagesOpening'
    | 'onMessagesOpeningChange'
    | 'onSelectNode'
    | 'actions'
>

const NODE_LOAD_ERRORS: Record<LoadFailure, string> = {
    not_found: 'This step could not be found. It may have been deleted, or it is outside the retention period.',
    failed: 'This step could not be loaded. Select it again to retry.',
}

interface NodeDetailArgs {
    node: TraceNodeApi
    load: NodeLoad
    tree: TraceNodeApi[]
    evaluationResults: TraceEvaluationResultApi[] | null
    evaluationResultsFailed: boolean
    person: string | null
    trace: { createdAt: string; sessionId: string | null }
}

function loadedContent(load: NodeLoad): NodeContent {
    switch (load.status) {
        case 'loading':
            return { kind: 'loading' }
        case 'error':
            return { kind: 'error', message: NODE_LOAD_ERRORS[load.failure] }
        case 'ready':
            return { kind: 'loaded', ...load.node.content }
    }
}

function nodeProperties(load: NodeLoad, node: TraceNodeApi, args: NodeDetailArgs): NodeProperties {
    if (node.kind === 'trace') {
        return {
            timestamp: args.trace.createdAt,
            provider: null,
            temperature: null,
            sessionId: args.trace.sessionId,
            promptName: null,
            promptVersion: null,
            person: args.person,
        }
    }
    const detail = load.status === 'ready' ? load.node : null
    return {
        timestamp: detail?.event?.timestamp ?? null,
        provider: detail?.metadata.provider ?? null,
        temperature: detail?.metadata.temperature ?? null,
        sessionId: detail?.metadata.sessionId ?? null,
        promptName: detail?.metadata.promptName ?? null,
        promptVersion: detail?.metadata.promptVersion ?? null,
        person: args.person,
    }
}

const EVALS_LOAD_ERROR = 'Evaluation results could not be loaded. Reload the page to try again.'

function evalsState(node: TraceNodeApi, args: NodeDetailArgs): EvalsState {
    if (args.evaluationResultsFailed) {
        return { status: 'error', errorMessage: EVALS_LOAD_ERROR }
    }
    if (!args.evaluationResults) {
        return { status: 'loading' }
    }
    const results =
        node.kind === 'trace'
            ? args.evaluationResults
            : args.evaluationResults.filter((result) => result.targetNodeId === node.id)
    return { status: 'ready', results: toEvalResults(results, { tree: args.tree, viewedNodeId: node.id }) }
}

export function toNodeDetail(args: NodeDetailArgs): NodeDetailData {
    const { node, load } = args
    return {
        node,
        content: loadedContent(load),
        error: load.status === 'ready' ? load.node.error : null,
        properties: nodeProperties(load, node, args),
        evals: evalsState(node, args),
    }
}
