import { EvaluationConfig, EvaluationRun } from '../../../evaluations/types'
import type { TraceNodeApi, TraceNodeDetailApi } from '../../../generated/api.schemas'
import { NodeDetailProps } from '../components/NodeDetail'
import { EvalsState, LoadFailure, NodeContent, NodeLoad, NodeProperties } from '../types'
import { NodeIO, readNodeIO } from './nodeIO'
import { TeamId } from './toAttachment'
import { toEvalResults } from './toEvalResults'
import { toMessageIO } from './toThread'
import { isMessageIO } from './toThreadMessages'

export type NodeDetailData = Omit<NodeDetailProps, 'tab' | 'onTabChange' | 'onViewInThread' | 'onSelectNode'>

const NODE_LOAD_ERRORS: Record<LoadFailure, string> = {
    not_found: 'This step could not be found. It may have been deleted, or it is outside the retention period.',
    failed: 'This step could not be loaded. Select it again to retry.',
}

interface NodeDetailArgs {
    node: TraceNodeApi
    load: NodeLoad
    tree: TraceNodeApi[]
    evalRuns: EvaluationRun[]
    evalRunsLoading: boolean
    evaluations: EvaluationConfig[]
    detectorEvaluationIds: string[]
    evaluationsSettled: boolean
    teamId: TeamId
    person: string | null
    trace: { createdAt: string; sessionId: string | null }
}

function ioContent(io: NodeIO, node: TraceNodeApi, teamId: TeamId): NodeContent {
    if (node.kind === 'generation' || isMessageIO(io.input, io.output)) {
        return { kind: 'messages', ...toMessageIO(io, node.id, teamId) }
    }
    return { kind: 'io', input: io.input, output: io.output }
}

function loadedContent(load: NodeLoad, node: TraceNodeApi, teamId: TeamId): NodeContent {
    switch (load.status) {
        case 'loading':
            return { kind: 'loading' }
        case 'error':
            return { kind: 'error', message: NODE_LOAD_ERRORS[load.failure] }
        case 'ready':
            return ioContent(readNodeIO(load.node), node, teamId)
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

function rawEvent(detail: TraceNodeDetailApi): Record<string, unknown> | null {
    const { event } = detail
    return event
        ? { event: event.name, uuid: event.uuid, timestamp: event.timestamp, properties: event.properties }
        : null
}

// Detector polarity comes from the evaluation configs, so results wait for them to avoid showing a flipped verdict.
function evalsState(runs: EvaluationRun[], node: TraceNodeApi, args: NodeDetailArgs): EvalsState {
    if (args.evalRunsLoading || !args.evaluationsSettled) {
        return { status: 'loading' }
    }
    return {
        status: 'ready',
        results: toEvalResults(runs, {
            tree: args.tree,
            viewedNodeId: node.id,
            evaluations: args.evaluations,
            detectorEvaluationIds: args.detectorEvaluationIds,
        }),
    }
}

export function toNodeDetail(args: NodeDetailArgs): NodeDetailData {
    const { node, load, evalRuns, teamId } = args
    const runs = node.kind === 'trace' ? evalRuns : evalRuns.filter((run) => run.generation_id === node.id)
    return {
        node,
        content: loadedContent(load, node, teamId),
        error: load.status === 'ready' ? load.node.error : null,
        properties: nodeProperties(load, node, args),
        evals: evalsState(runs, node, args),
        raw: load.status === 'ready' ? rawEvent(load.node) : null,
    }
}
