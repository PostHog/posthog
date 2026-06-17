// Presentational React Flow node for the data model DAG. Simplified port of
// frontend/src/scenes/data-warehouse/scene/modeling/Node.tsx — kea coupling, run /
// materialize actions, and ~/types imports removed.

import { Handle, Position } from '@xyflow/react'
import { type ReactElement } from 'react'

import { cn } from '@posthog/mcp-ui'

import { NODE_HEIGHT, NODE_WIDTH } from './autolayout'
import type { DataModelNode, DataModelNodeType, NodeRole } from './types'

const TYPE_SETTINGS: Record<DataModelNodeType, { label: string; className: string }> = {
    table: { label: 'table', className: 'text-muted-foreground border-muted-foreground/40 bg-muted-foreground/10' },
    view: { label: 'view', className: 'text-blue-600 border-blue-500/50 bg-blue-500/10' },
    matview: { label: 'matview', className: 'text-green-600 border-green-500/50 bg-green-500/10' },
    endpoint: { label: 'endpoint', className: 'text-purple-600 border-purple-500/50 bg-purple-500/10' },
}

const ROLE_RING: Record<NodeRole, string> = {
    focal: 'border-primary ring-2 ring-primary/40 shadow-md',
    upstream: 'border-blue-500/60',
    downstream: 'border-orange-500/60',
    other: 'border-border',
}

function statusDotClass(status?: string | null): string {
    switch (status) {
        case 'Completed':
            return 'bg-green-500'
        case 'Failed':
            return 'bg-red-500'
        case 'Cancelled':
            return 'bg-yellow-500'
        default:
            return 'bg-muted-foreground/40'
    }
}

export interface LineageNodeData extends Record<string, unknown> {
    node: DataModelNode
    role: NodeRole
    dimmed: boolean
}

export function LineageNode({ data }: { data: LineageNodeData }): ReactElement {
    const { node, role, dimmed } = data
    const typeSettings = TYPE_SETTINGS[node.type]

    return (
        <div
            className={cn(
                'flex flex-col justify-between rounded-lg border bg-background px-3 py-2 transition-opacity',
                ROLE_RING[role],
                dimmed ? 'opacity-40' : 'opacity-100'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
        >
            <Handle type="target" position={Position.Left} className="opacity-0" isConnectable={false} />
            <Handle type="source" position={Position.Right} className="opacity-0" isConnectable={false} />

            <div className="flex items-center justify-between gap-1">
                <span className={cn('rounded border px-1 text-[10px] uppercase tracking-wide', typeSettings.className)}>
                    {typeSettings.label}
                </span>
                {node.user_tag && (
                    <span className="truncate rounded border border-border px-1 text-[10px] text-muted-foreground">
                        #{node.user_tag}
                    </span>
                )}
            </div>

            <div className="truncate text-sm font-medium" title={node.name}>
                {node.name}
            </div>

            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                <span>
                    ↑{node.upstream_count} · ↓{node.downstream_count}
                </span>
                <span className="flex items-center gap-1" title={node.last_run_status ?? 'Never run'}>
                    <span className={cn('h-2 w-2 rounded-full', statusDotClass(node.last_run_status))} />
                    {node.sync_interval ?? '—'}
                </span>
            </div>
        </div>
    )
}

export const REACT_FLOW_NODE_TYPES = { model: LineageNode }
