import { useEffect, useRef } from 'react'

import { IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalRollupOutcome } from '../types'
import { EvalOutcomeMarker } from './EvalOutcomeMarker'
import { FeedbackMarker } from './FeedbackMarker'
import { NodeKindGlyph } from './NodeKindGlyph'
import { NodeStatsLine } from './NodeStatsLine'

export interface TraceTreeRowProps {
    node: TraceNodeApi
    depth: number
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onPrefetchNode: (id: string) => void
    evalOutcomes: Record<string, EvalRollupOutcome>
    /** Feedback entries per step id, trace-level ones on the root. */
    feedbackCountByNodeId?: Record<string, number>
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
    /** Changes on each step to a match, which scrolls the selected row into view. */
    matchStepCount?: number
}

export function TraceTreeRow({
    node,
    depth,
    selectedNodeId,
    onSelectNode,
    onPrefetchNode,
    evalOutcomes,
    feedbackCountByNodeId,
    matchingNodeIds = null,
    matchStepCount = 0,
}: TraceTreeRowProps): JSX.Element {
    const isSelected = node.id === selectedNodeId
    const rowRef = useRef<HTMLButtonElement>(null)
    useEffect(() => {
        if (isSelected && matchStepCount > 0) {
            rowRef.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [isSelected, matchStepCount])
    // Node ids come from free-form trace ids, so a name like "constructor" would read an inherited property.
    const evalOutcome = Object.hasOwn(evalOutcomes, node.id) ? evalOutcomes[node.id] : null
    const feedbackCount =
        feedbackCountByNodeId && Object.hasOwn(feedbackCountByNodeId, node.id) ? feedbackCountByNodeId[node.id] : 0
    return (
        <li>
            <button
                ref={rowRef}
                type="button"
                onClick={() => onSelectNode(node.id)}
                onMouseEnter={() => onPrefetchNode(node.id)}
                onFocus={() => onPrefetchNode(node.id)}
                aria-current={isSelected ? 'true' : undefined}
                data-attr="trace-view-tree-node"
                className={cn(
                    'flex w-full min-w-0 items-start gap-2 rounded py-1 pr-1.5 text-left hover:bg-fill-button-tertiary-hover',
                    isSelected && 'bg-fill-button-tertiary-active',
                    matchingNodeIds && !matchingNodeIds.has(node.id) && 'opacity-50'
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
                        {evalOutcome ? <EvalOutcomeMarker outcome={evalOutcome} /> : null}
                        {feedbackCount > 0 ? <FeedbackMarker count={feedbackCount} /> : null}
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
                            onPrefetchNode={onPrefetchNode}
                            evalOutcomes={evalOutcomes}
                            feedbackCountByNodeId={feedbackCountByNodeId}
                            matchingNodeIds={matchingNodeIds}
                            matchStepCount={matchStepCount}
                        />
                    ))}
                </ul>
            ) : null}
        </li>
    )
}
