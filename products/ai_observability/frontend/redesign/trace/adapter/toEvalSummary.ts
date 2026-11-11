import type { TraceEvaluationSummaryApi, TraceNodeApi } from '../../../generated/api.schemas'
import { EvalRollupOutcome, EvalsChipData } from '../types'
import { flattenTree } from './toTraceTree'

export function toEvalsChip({ passed, failed, unrated }: TraceEvaluationSummaryApi): EvalsChipData | null {
    return passed + failed + unrated === 0 ? null : { passed, graded: passed + failed, unrated }
}

export function toEvalOutcomesByNode(summary: TraceEvaluationSummaryApi): Record<string, EvalRollupOutcome> {
    return Object.fromEntries(summary.nodes.map(({ nodeId, outcome }) => [nodeId, outcome]))
}

export function firstFailingNodeId(tree: TraceNodeApi[], outcomes: Record<string, EvalRollupOutcome>): string | null {
    return flattenTree(tree).find((node) => outcomes[node.id] === 'fail')?.id ?? null
}
