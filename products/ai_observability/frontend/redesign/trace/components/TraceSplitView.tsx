import type { TraceNodeApi, TraceStepFeedbackApi } from '../../../generated/api.schemas'
import { EvalRollupOutcome, TreeStep } from '../types'
import { NodeDetail, NodeDetailProps } from './NodeDetail'
import { TraceTree } from './TraceTree'

export interface TraceSplitViewProps {
    tree: TraceNodeApi[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onStepNode: (step: TreeStep) => void
    onPrefetchNode: (id: string) => void
    detail: Omit<NodeDetailProps, 'onSelectNode' | 'highlightQuery' | 'matchStepCount'> | null
    evalOutcomes: ReadonlyMap<string, EvalRollupOutcome>
    stepFeedback?: ReadonlyMap<string, TraceStepFeedbackApi>
    matchingNodeIds?: ReadonlySet<string> | null
    highlightQuery?: string | null
    matchStepCount?: number
    treeRevealCount?: number
    showTraceKeys?: boolean
}

export function TraceSplitView({
    tree,
    selectedNodeId,
    onSelectNode,
    onStepNode,
    onPrefetchNode,
    detail,
    evalOutcomes,
    stepFeedback,
    matchingNodeIds = null,
    highlightQuery = null,
    matchStepCount = 0,
    treeRevealCount = 0,
    showTraceKeys = false,
}: TraceSplitViewProps): JSX.Element {
    return (
        <div className="@container h-full">
            <div className="flex flex-col gap-4 @3xl:h-full @3xl:flex-row">
                <aside className="w-full shrink-0 @3xl:w-72">
                    <TraceTree
                        nodes={tree}
                        selectedNodeId={selectedNodeId}
                        onSelectNode={onSelectNode}
                        onStepNode={onStepNode}
                        onPrefetchNode={onPrefetchNode}
                        evalOutcomes={evalOutcomes}
                        stepFeedback={stepFeedback}
                        matchingNodeIds={matchingNodeIds}
                        revealCount={treeRevealCount}
                        showTraceKeys={showTraceKeys}
                    />
                </aside>
                <div className="min-w-0 flex-1 @3xl:overflow-y-auto">
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
