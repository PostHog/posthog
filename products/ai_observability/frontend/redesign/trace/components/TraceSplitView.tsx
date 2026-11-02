import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalRollupOutcome } from '../types'
import { NodeDetail, NodeDetailProps } from './NodeDetail'
import { TraceTree } from './TraceTree'

export interface TraceSplitViewProps {
    tree: TraceNodeApi[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onPrefetchNode: (id: string) => void
    detail: Omit<NodeDetailProps, 'onSelectNode' | 'highlightQuery' | 'matchStepCount'> | null
    evalOutcomes: Record<string, EvalRollupOutcome>
    feedbackCountByNodeId?: Record<string, number>
    matchingNodeIds?: ReadonlySet<string> | null
    highlightQuery?: string | null
    matchStepCount?: number
}

export function TraceSplitView({
    tree,
    selectedNodeId,
    onSelectNode,
    onPrefetchNode,
    detail,
    evalOutcomes,
    feedbackCountByNodeId,
    matchingNodeIds = null,
    highlightQuery = null,
    matchStepCount = 0,
}: TraceSplitViewProps): JSX.Element {
    return (
        <div className="@container">
            <div className="flex flex-col gap-4 @3xl:flex-row @3xl:items-start">
                <aside className="w-full shrink-0 @3xl:w-72">
                    <TraceTree
                        nodes={tree}
                        selectedNodeId={selectedNodeId}
                        onSelectNode={onSelectNode}
                        onPrefetchNode={onPrefetchNode}
                        evalOutcomes={evalOutcomes}
                        feedbackCountByNodeId={feedbackCountByNodeId}
                        matchingNodeIds={matchingNodeIds}
                        matchStepCount={matchStepCount}
                    />
                </aside>
                <div className="min-w-0 flex-1 @3xl:sticky @3xl:top-[var(--scene-title-section-height,50px)] @3xl:max-h-[calc(100vh-var(--scene-title-section-height,50px))] @3xl:overflow-y-auto">
                    {detail ? (
                        <NodeDetail
                            {...detail}
                            onSelectNode={onSelectNode}
                            highlightQuery={highlightQuery}
                            matchStepCount={matchStepCount}
                        />
                    ) : (
                        <p className="m-0 text-secondary">Select a step to see its details.</p>
                    )}
                </div>
            </div>
        </div>
    )
}
