import { IconDatabase } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DataModelingNodeType } from '~/types'

import { CreateModelNodeType } from './types'

const NODE_TYPE_COLORS: Record<DataModelingNodeType, string> = {
    table: 'var(--muted)',
    view: 'var(--primary-3000)',
    matview: 'var(--success)',
}

const NODES_TO_SHOW: CreateModelNodeType[] = [
    {
        type: 'view',
        name: 'View',
        description: 'A virtual table based on a SQL query',
    },
    {
        type: 'matview',
        name: 'Materialized view',
        description: 'A persisted view with improved query performance',
    },
]

function DraggableNodeButton({ node }: { node: CreateModelNodeType }): JSX.Element {
    const color = NODE_TYPE_COLORS[node.type]

    return (
        <div draggable>
            <LemonButton
                icon={
                    <span style={{ color }}>
                        <IconDatabase />
                    </span>
                }
                fullWidth
            >
                <div className="flex flex-col items-start flex-1">
                    <span>{node.name}</span>
                    {node.description && <span className="text-xs text-muted font-normal">{node.description}</span>}
                </div>
            </LemonButton>
        </div>
    )
}

export function DataModelingEditorPanel(): JSX.Element {
    return (
        <div className="absolute right-4 top-4 bottom-4 w-64 bg-primary border rounded-lg shadow-lg overflow-hidden z-10">
            <div className="flex flex-col gap-1 p-2">
                <span className="flex gap-2 text-xs font-semibold mt-2 items-center text-muted">Node types</span>
                {NODES_TO_SHOW.map((node, index) => (
                    <DraggableNodeButton key={`${node.type}-${index}`} node={node} />
                ))}
            </div>
        </div>
    )
}
