import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalRollupOutcome } from '../types'
import { TraceTreeRow } from './TraceTreeRow'

export interface TraceTreeProps {
    nodes: TraceNodeApi[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onPrefetchNode: (id: string) => void
    evalOutcomes: Record<string, EvalRollupOutcome>
    feedbackCountByNodeId?: Record<string, number>
    matchingNodeIds?: ReadonlySet<string> | null
    matchStepCount?: number
}

export function TraceTree({
    nodes,
    selectedNodeId,
    onSelectNode,
    onPrefetchNode,
    evalOutcomes,
    feedbackCountByNodeId,
    matchingNodeIds = null,
    matchStepCount = 0,
}: TraceTreeProps): JSX.Element {
    return (
        <ul aria-label="Trace steps" className="m-0 list-none rounded border border-primary bg-surface-primary p-1">
            {nodes.map((node) => (
                <TraceTreeRow
                    key={node.id}
                    node={node}
                    depth={0}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={onSelectNode}
                    onPrefetchNode={onPrefetchNode}
                    evalOutcomes={evalOutcomes}
                    feedbackCountByNodeId={feedbackCountByNodeId}
                    matchingNodeIds={matchingNodeIds}
                    matchStepCount={matchStepCount}
                />
            ))}
        </ul>
    )
}
