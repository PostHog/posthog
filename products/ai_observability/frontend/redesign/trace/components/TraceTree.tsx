import type { TraceNodeApi } from '../../../generated/api.schemas'
import { TraceTreeRow } from './TraceTreeRow'

export interface TraceTreeProps {
    nodes: TraceNodeApi[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
}

export function TraceTree({ nodes, selectedNodeId, onSelectNode }: TraceTreeProps): JSX.Element {
    return (
        <ul aria-label="Trace steps" className="m-0 list-none rounded border border-primary bg-surface-primary p-1">
            {nodes.map((node) => (
                <TraceTreeRow
                    key={node.id}
                    node={node}
                    depth={0}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={onSelectNode}
                />
            ))}
        </ul>
    )
}
