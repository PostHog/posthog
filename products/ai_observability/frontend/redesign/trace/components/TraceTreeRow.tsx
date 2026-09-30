import { IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { TraceTreeNode } from '../types'
import { NodeKindGlyph } from './NodeKindGlyph'
import { NodeStatsLine } from './NodeStatsLine'

export interface TraceTreeRowProps {
    node: TraceTreeNode
    depth: number
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
}

export function TraceTreeRow({ node, depth, selectedNodeId, onSelectNode }: TraceTreeRowProps): JSX.Element {
    const isSelected = node.id === selectedNodeId
    return (
        <li>
            <button
                type="button"
                onClick={() => onSelectNode(node.id)}
                aria-current={isSelected ? 'true' : undefined}
                data-attr="trace-view-tree-node"
                className={cn(
                    'flex w-full min-w-0 items-start gap-2 rounded py-1 pr-1.5 text-left hover:bg-fill-button-tertiary-hover',
                    isSelected && 'bg-fill-button-tertiary-active'
                )}
                // Depth is data, so the indent cannot be a static Tailwind class.
                style={{ paddingLeft: `${0.375 + depth * 0.75}rem` }}
            >
                <NodeKindGlyph kind={node.kind} />
                <span className="flex min-w-0 flex-col">
                    <span
                        className={cn(
                            'flex min-w-0 items-center gap-1 text-sm',
                            isSelected ? 'font-semibold' : 'font-medium',
                            node.hasError && 'text-danger'
                        )}
                    >
                        <span className="truncate">{node.name}</span>
                        {node.hasError ? <IconWarning className="shrink-0" role="img" aria-label="Error" /> : null}
                    </span>
                    <NodeStatsLine stats={node.stats} model={node.model} compact />
                </span>
            </button>
            {node.children.length > 0 ? (
                <ul className="m-0 list-none p-0">
                    {node.children.map((child) => (
                        <TraceTreeRow
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            selectedNodeId={selectedNodeId}
                            onSelectNode={onSelectNode}
                        />
                    ))}
                </ul>
            ) : null}
        </li>
    )
}
