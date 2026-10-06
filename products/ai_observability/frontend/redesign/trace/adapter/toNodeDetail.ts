import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { AIData } from '../../../aiObservabilityAIDataLogic'
import { EvaluationConfig, EvaluationRun } from '../../../evaluations/types'
import type { TraceNodeApi } from '../../../generated/api.schemas'
import { isLLMEvent } from '../../../utils'
import { NodeDetailProps } from '../components/NodeDetail'
import { EvalsState, NodeContent, NodeProperties } from '../types'
import { resolveEventIO } from './eventIO'
import { readNumber, readString } from './propertyReaders'
import { TeamId } from './toAttachment'
import { toEvalResults } from './toEvalResults'
import { toMessageIO } from './toThread'
import { isMessageIO } from './toThreadMessages'
import { eventError } from './toTraceTree'

export type NodeDetailData = Omit<NodeDetailProps, 'tab' | 'onTabChange' | 'onViewInThread' | 'onSelectNode'>

interface NodeDetailArgs {
    trace: LLMTrace
    event: LLMTrace | LLMTraceEvent
    node: TraceNodeApi
    cache: Record<string, AIData | null>
    tree: TraceNodeApi[]
    evalRuns: EvaluationRun[]
    evalRunsLoading: boolean
    evaluations: EvaluationConfig[]
    detectorEvaluationIds: string[]
    evaluationsSettled: boolean
    teamId: TeamId
    person: string | null
}

function ioContent(io: { input: unknown; output: unknown }, node: TraceNodeApi, teamId: TeamId): NodeContent {
    if (node.kind === 'generation' || isMessageIO(io.input, io.output)) {
        return { kind: 'messages', ...toMessageIO(io, node.id, teamId) }
    }
    return { kind: 'io', input: io.input, output: io.output }
}

function eventContent(
    event: LLMTraceEvent,
    node: TraceNodeApi,
    cache: Record<string, AIData | null>,
    teamId: TeamId
): NodeContent {
    const io = resolveEventIO(event, cache)
    return io.loading ? { kind: 'loading' } : ioContent(io, node, teamId)
}

function eventProperties(event: LLMTraceEvent, person: string | null): NodeProperties {
    const properties = event.properties
    return {
        timestamp: event.createdAt,
        provider: readString(properties.$ai_provider),
        temperature: readNumber(properties.$ai_temperature),
        sessionId: readString(properties.$ai_session_id),
        promptName: readString(properties.$ai_prompt_name),
        promptVersion: readNumber(properties.$ai_prompt_version),
        person,
    }
}

function traceProperties(trace: LLMTrace, person: string | null): NodeProperties {
    return {
        timestamp: trace.createdAt,
        provider: null,
        temperature: null,
        sessionId: trace.aiSessionId ?? null,
        promptName: null,
        promptVersion: null,
        person,
    }
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
    const { trace, event, node, cache, evalRuns, teamId, person } = args
    const runs = node.kind === 'trace' ? evalRuns : evalRuns.filter((run) => run.generation_id === node.id)
    const evals = evalsState(runs, node, args)

    if (!isLLMEvent(event)) {
        const { events: _events, ...raw } = trace
        return {
            node,
            content: ioContent({ input: trace.inputState, output: trace.outputState }, node, teamId),
            error: null,
            properties: traceProperties(trace, person),
            evals,
            raw,
        }
    }
    return {
        node,
        content: eventContent(event, node, cache, teamId),
        error: eventError(event),
        properties: eventProperties(event, person),
        evals,
        raw: { event: event.event, id: event.id, createdAt: event.createdAt, properties: event.properties },
    }
}
