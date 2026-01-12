import { IconDatabase, IconDrag } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

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

function NodeTypeButton({ node }: { node: CreateModelNodeType }): JSX.Element {
    const color = NODE_TYPE_COLORS[node.type]

    return (
        <LemonButton
            icon={
                <span style={{ color }}>
                    <IconDatabase />
                </span>
            }
            sideIcon={<IconDrag />}
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
            <div className="p-3 border-b">
                <h3 className="font-semibold text-sm">Add nodes</h3>
                <p className="text-xs text-muted">Drag nodes onto the canvas</p>
            </div>
            <div className="flex flex-col gap-1 p-2">
                <span className="flex gap-2 text-xs font-semibold mt-2 items-center text-muted">
                    Node types <LemonDivider className="flex-1" />
                </span>
                {NODES_TO_SHOW.map((node, index) => (
                    <NodeTypeButton key={`${node.type}-${index}`} node={node} />
                ))}
            </div>
        </div>
    )
}
