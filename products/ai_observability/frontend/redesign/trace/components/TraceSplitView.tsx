import { TraceTreeNode } from '../types'
import { NodeDetail, NodeDetailProps } from './NodeDetail'
import { TraceTree } from './TraceTree'

export interface TraceSplitViewProps {
    tree: TraceTreeNode[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    detail: Omit<NodeDetailProps, 'onSelectNode'> | null
}

export function TraceSplitView({ tree, selectedNodeId, onSelectNode, detail }: TraceSplitViewProps): JSX.Element {
    return (
        <div className="@container">
            <div className="flex flex-col gap-4 @3xl:flex-row @3xl:items-start">
                <aside className="w-full shrink-0 @3xl:w-72">
                    <TraceTree nodes={tree} selectedNodeId={selectedNodeId} onSelectNode={onSelectNode} />
                </aside>
                <div className="min-w-0 flex-1 @3xl:sticky @3xl:top-[var(--scene-title-section-height,50px)] @3xl:max-h-[calc(100vh-var(--scene-title-section-height,50px))] @3xl:overflow-y-auto">
                    {detail ? (
                        <NodeDetail {...detail} onSelectNode={onSelectNode} />
                    ) : (
                        <p className="m-0 text-secondary">Select a step to see its details.</p>
                    )}
                </div>
            </div>
        </div>
    )
}
