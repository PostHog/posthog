import { useId } from 'react'

import { IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import type { TraceNodeApi, TraceStepFeedbackApi } from '../../../generated/api.schemas'
import { EvalRollupOutcome } from '../types'
import { EvalOutcomeMarker } from './EvalOutcomeMarker'
import { FeedbackMarker } from './FeedbackMarker'
import { NodeKindGlyph } from './NodeKindGlyph'
import { NodeStatsLine } from './NodeStatsLine'

export interface TraceTreeRowProps {
    node: TraceNodeApi
    depth: number
    /** The 1-based place of the step among its siblings, and how many siblings there are. */
    positionInSet: number
    setSize: number
    selectedNodeId: string | null
    /** The one row Tab lands on: the selected step, or the first step when none is selected. */
    tabStopId: string | null
    onSelectNode: (id: string) => void
    onPrefetchNode: (id: string) => void
    evalOutcomes: ReadonlyMap<string, EvalRollupOutcome>
    /** Feedback entries per step id, trace-level ones on the root. */
    stepFeedback?: ReadonlyMap<string, TraceStepFeedbackApi>
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
}

// A step with children owns their group, which sits beside the row and not inside it. The tree has no collapsed steps.
function parentAttributes(groupId: string, hasChildren: boolean): { 'aria-owns'?: string; 'aria-expanded'?: true } {
    return hasChildren ? { 'aria-owns': groupId, 'aria-expanded': true } : {}
}

export function TraceTreeRow({
    node,
    depth,
    positionInSet,
    setSize,
    selectedNodeId,
    tabStopId,
    onSelectNode,
    onPrefetchNode,
    evalOutcomes,
    stepFeedback,
    matchingNodeIds = null,
}: TraceTreeRowProps): JSX.Element {
    const isSelected = node.id === selectedNodeId
    const groupId = useId()
    const hasChildren = node.children.length > 0
    const evalOutcome = evalOutcomes.get(node.id) ?? null
    const feedbackCount = stepFeedback?.get(node.id)?.total ?? 0
    return (
        <li role="none">
            <button
                type="button"
                role="treeitem"
                aria-selected={isSelected}
                aria-level={depth + 1}
                aria-posinset={positionInSet}
                aria-setsize={setSize}
                {...parentAttributes(groupId, hasChildren)}
                tabIndex={node.id === tabStopId ? 0 : -1}
                onClick={() => onSelectNode(node.id)}
                onMouseEnter={() => onPrefetchNode(node.id)}
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
            {hasChildren ? (
                <ul id={groupId} role="group" className="m-0 list-none p-0">
                    {node.children.map((child, index) => (
                        <TraceTreeRow
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            positionInSet={index + 1}
                            setSize={node.children.length}
                            selectedNodeId={selectedNodeId}
                            tabStopId={tabStopId}
                            onSelectNode={onSelectNode}
                            onPrefetchNode={onPrefetchNode}
                            evalOutcomes={evalOutcomes}
                            stepFeedback={stepFeedback}
                            matchingNodeIds={matchingNodeIds}
                        />
                    ))}
                </ul>
            ) : null}
        </li>
    )
}
