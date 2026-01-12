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
        description: 'An ephemeral view for repeatable query execution',
    },
    {
        type: 'matview',
        name: 'Materialized view',
        description: 'A persisted view that reduces query overhead',
    },
]

function NodeTypeButton({ node }: { node: CreateModelNodeType }): JSX.Element {
    const color = NODE_TYPE_COLORS[node.type]

    return (
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
    )
}

export function DataModelingEditorPanel(): JSX.Element {
    return (
        <div className="absolute right-4 top-4 bottom-4 w-64 bg-surface-light border rounded-lg shadow-lg overflow-hidden z-10">
            <div className="flex flex-col gap-1 p-2">
                {NODES_TO_SHOW.map((node, index) => (
                    <NodeTypeButton key={`${node.type}-${index}`} node={node} />
                ))}
            </div>
        </div>
    )
}
