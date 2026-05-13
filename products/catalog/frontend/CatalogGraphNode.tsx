import { Handle, NodeProps, Position } from '@xyflow/react'

import { IconCheckCircle, IconDatabase, IconServer, IconWarning } from '@posthog/icons'

import type { CatalogGraphNodeData } from './catalogGraphSceneLogic'
import { GRAPH_NODE_HEIGHT, GRAPH_NODE_WIDTH } from './graphAutolayout'

const KIND_ICONS: Record<string, JSX.Element> = {
    warehouse_table: <IconDatabase />,
    saved_query: <IconServer />,
    system_table: <IconServer />,
    posthog_table: <IconServer />,
}

const STATUS_ICON: Record<string, JSX.Element | null> = {
    proposed: null,
    approved: <IconCheckCircle className="text-primary" />,
    official: <IconCheckCircle className="text-success" />,
    drift: <IconWarning className="text-warning" />,
}

function confidenceColor(confidence: number | null): string {
    if (confidence === null || confidence === undefined) {
        return 'var(--border)'
    }
    if (confidence >= 0.8) {
        return 'var(--success)'
    }
    if (confidence >= 0.5) {
        return 'var(--warning)'
    }
    return 'var(--danger)'
}

export function CatalogGraphNode({ data }: NodeProps<{ data: CatalogGraphNodeData }>): JSX.Element {
    const { node, domainColor } = data
    const kindIcon = KIND_ICONS[node.kind] ?? <IconDatabase />
    const statusIcon = STATUS_ICON[node.status] ?? null

    return (
        <div
            className="rounded bg-bg-light text-text-3000 shadow-sm hover:shadow-md transition-shadow overflow-hidden"
            style={{
                width: GRAPH_NODE_WIDTH,
                height: GRAPH_NODE_HEIGHT,
                borderLeft: `4px solid ${domainColor}`,
                border: '1px solid var(--border)',
                borderLeftWidth: 4,
                borderLeftColor: domainColor,
            }}
        >
            {/* Force-directed layouts pick edge angles freely, so we expose a
                source+target handle on every side and let React Flow choose. */}
            <Handle type="target" id="t-top" position={Position.Top} className="!opacity-0" isConnectable={false} />
            <Handle type="source" id="s-top" position={Position.Top} className="!opacity-0" isConnectable={false} />
            <Handle type="target" id="t-right" position={Position.Right} className="!opacity-0" isConnectable={false} />
            <Handle type="source" id="s-right" position={Position.Right} className="!opacity-0" isConnectable={false} />
            <Handle
                type="target"
                id="t-bottom"
                position={Position.Bottom}
                className="!opacity-0"
                isConnectable={false}
            />
            <Handle
                type="source"
                id="s-bottom"
                position={Position.Bottom}
                className="!opacity-0"
                isConnectable={false}
            />
            <Handle type="target" id="t-left" position={Position.Left} className="!opacity-0" isConnectable={false} />
            <Handle type="source" id="s-left" position={Position.Left} className="!opacity-0" isConnectable={false} />
            <div className="flex flex-col gap-1 px-3 py-2 h-full">
                <div className="flex items-center gap-2">
                    <span className="text-secondary text-sm shrink-0">{kindIcon}</span>
                    <span className="font-mono text-xs truncate flex-1" title={node.name}>
                        {node.name}
                    </span>
                    {statusIcon && <span className="text-sm shrink-0">{statusIcon}</span>}
                    <span
                        className="rounded-full shrink-0"
                        style={{ width: 8, height: 8, background: confidenceColor(node.confidence) }}
                        title={
                            node.confidence !== null ? `Confidence ${node.confidence.toFixed(2)}` : 'Unknown confidence'
                        }
                    />
                </div>
                <div className="text-xs text-secondary line-clamp-2 leading-snug" title={node.description ?? ''}>
                    {node.description || (node.business_domain ? node.business_domain : 'No description')}
                </div>
            </div>
        </div>
    )
}
