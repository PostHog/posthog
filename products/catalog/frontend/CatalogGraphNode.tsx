import { Handle, NodeProps, Position } from '@xyflow/react'

import { IconCheckCircle, IconDatabase, IconServer, IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import type { CatalogGraphNodeData } from './catalogGraphSceneLogic'
import { GRAPH_NODE_HEIGHT, GRAPH_NODE_WIDTH } from './graphAutolayout'

const KIND_ICONS: Record<string, JSX.Element> = {
    warehouse_table: <IconDatabase />,
    saved_query: <IconServer />,
    system_table: <IconServer />,
    posthog_table: <IconServer />,
}

const KIND_LABEL: Record<string, string> = {
    warehouse_table: 'Warehouse',
    saved_query: 'Saved query',
    system_table: 'System',
    posthog_table: 'PostHog',
}

const STATUS_INLINE_ICON: Record<string, JSX.Element | null> = {
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

const HANDLE_CONFIG = [
    ['target', 't-top', Position.Top],
    ['source', 's-top', Position.Top],
    ['target', 't-right', Position.Right],
    ['source', 's-right', Position.Right],
    ['target', 't-bottom', Position.Bottom],
    ['source', 's-bottom', Position.Bottom],
    ['target', 't-left', Position.Left],
    ['source', 's-left', Position.Left],
] as const

export function CatalogGraphNode({ data }: NodeProps<{ data: CatalogGraphNodeData }>): JSX.Element {
    const { node, domainColor } = data
    const kindIcon = KIND_ICONS[node.kind] ?? <IconDatabase />
    const kindLabel = KIND_LABEL[node.kind] ?? node.kind
    const inlineStatus = STATUS_INLINE_ICON[node.status] ?? null
    const hasDomain = !!node.business_domain

    return (
        <div
            className="group rounded-md bg-bg-light text-text-3000 shadow-sm hover:shadow-md transition-shadow overflow-hidden flex flex-col"
            style={{
                width: GRAPH_NODE_WIDTH,
                height: GRAPH_NODE_HEIGHT,
                border: '1px solid var(--border)',
                borderLeftWidth: 4,
                borderLeftColor: hasDomain ? domainColor : 'var(--border)',
            }}
        >
            {/* Force-directed layouts pick edge angles freely, so we expose a
                source+target handle on every side and let React Flow choose. */}
            {HANDLE_CONFIG.map(([type, id, position]) => (
                <Handle key={id} type={type} id={id} position={position} className="!opacity-0" isConnectable={false} />
            ))}
            <div className="flex items-center gap-2 px-3 pt-2">
                <span className="text-secondary text-base shrink-0">{kindIcon}</span>
                <span className="font-mono text-sm font-semibold truncate flex-1" title={node.name}>
                    {node.name}
                </span>
                {inlineStatus && <span className="text-base shrink-0">{inlineStatus}</span>}
            </div>
            <div className="flex-1 px-3 pt-1 overflow-hidden">
                {node.description ? (
                    <div className="text-xs text-secondary line-clamp-2 leading-snug" title={node.description}>
                        {node.description}
                    </div>
                ) : (
                    <div className="text-xs text-secondary italic">No description yet</div>
                )}
            </div>
            <div className="flex items-center gap-1 px-3 py-1.5 border-t bg-bg-3000/40 text-xs">
                <span className="text-secondary">{kindLabel}</span>
                <span className="text-secondary">·</span>
                <span className="text-secondary">
                    {node.columns.length} col{node.columns.length === 1 ? '' : 's'}
                </span>
                <span className="flex-1" />
                <LemonTag size="small" type={STATUS_COLOR[node.status] ?? 'default'}>
                    {STATUS_LABEL[node.status] ?? node.status}
                </LemonTag>
                <span
                    className="rounded-full shrink-0 ml-1"
                    style={{ width: 8, height: 8, background: confidenceColor(node.confidence) }}
                    title={
                        node.confidence !== null && node.confidence !== undefined
                            ? `Confidence ${node.confidence.toFixed(2)}`
                            : 'Unknown confidence'
                    }
                />
            </div>
        </div>
    )
}
