import { KeyboardEvent, useEffect, useRef } from 'react'

import type { TraceNodeApi, TraceStepFeedbackApi } from '../../../generated/api.schemas'
import { findTreeNode, flattenTree } from '../traceTreeLookups'
import { EvalRollupOutcome, TreeStep } from '../types'
import { TraceTreeKeyLegend } from './TraceTreeKeyLegend'
import { TraceTreeRow } from './TraceTreeRow'

export interface TraceTreeProps {
    nodes: TraceNodeApi[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onStepNode: (step: TreeStep) => void
    onPrefetchNode: (id: string) => void
    evalOutcomes: ReadonlyMap<string, EvalRollupOutcome>
    stepFeedback?: ReadonlyMap<string, TraceStepFeedbackApi>
    matchingNodeIds?: ReadonlySet<string> | null
    /** Changes on each step to a match or by key, which scrolls the selected row into view and announces it. */
    revealCount?: number
    showTraceKeys?: boolean
}

// The keys of the WAI-ARIA tree view pattern. The tree has no collapsed steps, so left and right only move.
const KEY_STEPS: Partial<Record<string, TreeStep>> = {
    ArrowDown: 'next',
    ArrowUp: 'previous',
    ArrowLeft: 'parent',
    ArrowRight: 'child',
    Home: 'first',
    End: 'last',
}

export function TraceTree({
    nodes,
    selectedNodeId,
    onSelectNode,
    onStepNode,
    onPrefetchNode,
    evalOutcomes,
    stepFeedback,
    matchingNodeIds = null,
    revealCount = 0,
    showTraceKeys = false,
}: TraceTreeProps): JSX.Element {
    const treeRef = useRef<HTMLUListElement>(null)
    const announcementRef = useRef<HTMLSpanElement>(null)
    const selectedNode = selectedNodeId ? findTreeNode(nodes, selectedNodeId) : null
    const tabStopId = selectedNode?.id ?? nodes[0]?.id ?? null

    useEffect(() => {
        const tree = treeRef.current
        const row = tree?.querySelector<HTMLElement>('[aria-selected="true"]')
        if (!tree || !row || !selectedNode) {
            return
        }
        const focusIsInTree = tree.contains(document.activeElement)
        if (focusIsInTree) {
            row.focus()
        }
        if (revealCount > 0) {
            row.scrollIntoView({ block: 'nearest' })
            // A screen reader reads the row that takes focus. A key pressed elsewhere moves no focus, so it is told.
            if (!focusIsInTree && announcementRef.current) {
                const steps = flattenTree(nodes)
                const position = steps.indexOf(selectedNode) + 1
                announcementRef.current.textContent = `${selectedNode.name}, step ${position} of ${steps.length}`
            }
        }
        // The selection and the count say when to reveal. The tree itself changes on unrelated reads.
        // oxlint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedNode?.id, revealCount])

    const stepOnKey = (event: KeyboardEvent): void => {
        const step = KEY_STEPS[event.key]
        if (!step || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
            return
        }
        // The key would otherwise scroll the tree under the selection.
        event.preventDefault()
        onStepNode(step)
    }
    return (
        <div className="flex max-h-full flex-col rounded border border-primary bg-surface-primary">
            <ul
                ref={treeRef}
                role="tree"
                aria-label="Trace steps"
                className="m-0 min-h-0 list-none overflow-y-auto p-1"
                onKeyDown={stepOnKey}
                data-attr="trace-view-tree"
            >
                {nodes.map((node, index) => (
                    <TraceTreeRow
                        key={node.id}
                        node={node}
                        depth={0}
                        positionInSet={index + 1}
                        setSize={nodes.length}
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
            <span ref={announcementRef} className="sr-only" aria-live="polite" />
            <TraceTreeKeyLegend showTraceKeys={showTraceKeys} />
        </div>
    )
}
