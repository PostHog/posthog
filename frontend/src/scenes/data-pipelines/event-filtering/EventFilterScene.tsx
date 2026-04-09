import {
    DndContext,
    DragEndEvent,
    DragOverlay,
    DragStartEvent,
    MouseSensor,
    TouchSensor,
    pointerWithin,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { arrayMove } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useCallback, useMemo, useState } from 'react'

import { LemonButton, LemonDivider, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    eventFilterLogic,
    EVENT_FILTER_MAX_CONDITIONS,
    EVENT_FILTER_MAX_DEPTH,
    FilterNode,
    TreePath,
} from './eventFilterLogic'
import { EventFilterMetrics } from './EventFilterMetrics'
import { EventFilterTestCases } from './EventFilterTestCases'
import { NodeEditor } from './EventFilterTreeEditor'
import {
    buildNidIndex,
    filterTreeToExpression,
    getNodeAtPath,
    isAncestorPath,
    isTreeEmpty,
    nodeSummary,
    splitParentChild,
    stampNids,
} from './eventFilterTreeUtils'

export const scene: SceneExport = {
    component: EventFilterScene,
    logic: eventFilterLogic,
}

export function EventFilterScene(): JSX.Element {
    const { filterForm, isFilterFormSubmitting, allTestsPass, filterFormErrors, showFilterFormErrors } =
        useValues(eventFilterLogic)
    const { setFilterFormValue, submitFilterForm, updateTreeNode } = useActions(eventFilterLogic)
    const [activeId, setActiveId] = useState<string | null>(null)
    const [showExpression, setShowExpression] = useState(false)

    // Stamp stable IDs on tree nodes (mutates in place, idempotent)
    stampNids(filterForm.filter_tree as FilterNode & { _nid?: string })

    // Build nid → path index on every render
    const nidIndex = useMemo(() => buildNidIndex(filterForm.filter_tree), [filterForm.filter_tree])

    const sensors = useSensors(
        useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
        useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } })
    )

    const handleDragStart = useCallback((event: DragStartEvent) => {
        setActiveId(event.active.id as string)
    }, [])

    const handleDragEnd = useCallback(
        (event: DragEndEvent) => {
            setActiveId(null)
            const { active, over } = event
            if (!over || active.id === over.id) {
                return
            }

            const activeNid = active.id as string
            const overIdStr = over.id as string
            const tree = filterForm.filter_tree
            const idx = buildNidIndex(tree)

            const activePath = idx.get(activeNid)
            if (!activePath) {
                return
            }
            const activeParent = splitParentChild(activePath)
            if (!activeParent) {
                return
            }

            // Determine target
            let targetGroupPath: TreePath
            let insertIndex: number

            if (overIdStr.startsWith('drop:')) {
                // Dropped on a group droppable — append at end
                const groupNid = overIdStr.slice(5)
                const groupPath = idx.get(groupNid)
                if (!groupPath) {
                    return
                }
                targetGroupPath = groupPath
                const targetNode = groupPath.length === 0 ? tree : getNodeAtPath(tree, groupPath)
                if (!targetNode || (targetNode.type !== 'and' && targetNode.type !== 'or')) {
                    return
                }
                insertIndex = targetNode.children.length
            } else {
                // Dropped on a sortable item — insert at its position
                const overPath = idx.get(overIdStr)
                if (!overPath) {
                    return
                }
                const overParent = splitParentChild(overPath)
                if (!overParent) {
                    return
                }
                targetGroupPath = overParent.parentPath
                insertIndex = overParent.childIndex
            }

            // Prevent dropping into own descendant
            if (isAncestorPath(activePath, targetGroupPath)) {
                return
            }

            const sameGroup = activeParent.parentPath.join('.') === targetGroupPath.join('.')

            if (sameGroup) {
                // Reorder within same group
                const parentNode =
                    activeParent.parentPath.length === 0 ? tree : getNodeAtPath(tree, activeParent.parentPath)
                if (!parentNode || (parentNode.type !== 'and' && parentNode.type !== 'or')) {
                    return
                }
                const newChildren = arrayMove([...parentNode.children], activeParent.childIndex, insertIndex)
                updateTreeNode(activeParent.parentPath, { ...parentNode, children: newChildren })
            } else {
                // Move between groups
                const srcParent =
                    activeParent.parentPath.length === 0 ? tree : getNodeAtPath(tree, activeParent.parentPath)
                if (!srcParent || (srcParent.type !== 'and' && srcParent.type !== 'or')) {
                    return
                }

                const movedNode = srcParent.children[activeParent.childIndex]
                const newTree = JSON.parse(JSON.stringify(tree))

                // Remove from source first
                const newSrc =
                    activeParent.parentPath.length === 0 ? newTree : getNodeAtPath(newTree, activeParent.parentPath)
                if (newSrc && (newSrc.type === 'and' || newSrc.type === 'or')) {
                    newSrc.children.splice(activeParent.childIndex, 1)
                }

                // Recompute target path after removal (indices may have shifted)
                stampNids(newTree as FilterNode & { _nid?: string })
                const newIdx = buildNidIndex(newTree)
                let destGroupPath: TreePath
                let destIndex: number

                if (overIdStr.startsWith('drop:')) {
                    const groupNid2 = overIdStr.slice(5)
                    destGroupPath = newIdx.get(groupNid2) ?? targetGroupPath
                    const destNode = destGroupPath.length === 0 ? newTree : getNodeAtPath(newTree, destGroupPath)
                    destIndex = destNode?.children?.length ?? 0
                } else {
                    const overPath2 = newIdx.get(overIdStr)
                    if (!overPath2) {
                        return
                    }
                    const overParent2 = splitParentChild(overPath2)
                    if (!overParent2) {
                        return
                    }
                    destGroupPath = overParent2.parentPath
                    destIndex = overParent2.childIndex
                }

                const newDst = destGroupPath.length === 0 ? newTree : getNodeAtPath(newTree, destGroupPath)
                if (newDst && (newDst.type === 'and' || newDst.type === 'or')) {
                    newDst.children.splice(destIndex, 0, JSON.parse(JSON.stringify(movedNode)))
                }

                setFilterFormValue('filter_tree', newTree)
            }
        },
        [filterForm.filter_tree, updateTreeNode, setFilterFormValue]
    )

    const activeNode = activeId ? getNodeAtPath(filterForm.filter_tree, nidIndex.get(activeId) ?? []) : null

    return (
        <SceneContent>
            <SceneTitleSection
                name="Event filtering"
                description="Drop events at ingestion time based on event name or distinct ID."
                resourceType={{ type: 'data_pipeline' }}
            />
            <Form logic={eventFilterLogic} formKey="filterForm" enableFormOnSubmit>
                <div className="space-y-4">
                    <div className="border rounded p-3 text-sm">
                        <p className="mb-1">
                            Event filtering is the most efficient way to drop unwanted events. Filters are evaluated
                            early in the ingestion pipeline, before transformations run.
                        </p>
                        <p className="mb-0">
                            Events that pass these filters will still go through any active{' '}
                            <strong>transformations</strong>, which can also drop or modify events. Use event filters
                            for simple drop rules based on event name or distinct ID, and only use transformations when
                            you need more complex logic.
                        </p>
                    </div>

                    <div
                        className={`border rounded p-3 flex items-center justify-between ${
                            filterForm.mode === 'live'
                                ? 'border-success'
                                : filterForm.mode === 'dry_run'
                                  ? 'border-warning'
                                  : ''
                        }`}
                    >
                        <div>
                            <div className="font-semibold">
                                {filterForm.mode === 'live'
                                    ? 'Filter is active'
                                    : filterForm.mode === 'dry_run'
                                      ? 'Filter is in dry run'
                                      : 'Filter is disabled'}
                            </div>
                            <div className="text-muted text-sm">
                                {filterForm.mode === 'live'
                                    ? 'Matching events are being dropped from ingestion.'
                                    : filterForm.mode === 'dry_run'
                                      ? 'Matching events are counted but not dropped. Use this to verify your filter before going live.'
                                      : 'No events are being filtered or counted.'}
                            </div>
                            {filterForm.mode === 'live' && !allTestsPass && filterForm.test_cases.length > 0 && (
                                <div className="text-danger text-xs mt-1">Tests failing — will be saved as dry run</div>
                            )}
                        </div>
                        <LemonSelect
                            size="small"
                            options={[
                                { value: 'disabled', label: 'Disabled' },
                                { value: 'dry_run', label: 'Dry run' },
                                { value: 'live', label: 'Live' },
                            ]}
                            value={filterForm.mode}
                            onChange={(value) => {
                                if (value === 'live' && !allTestsPass && filterForm.test_cases.length > 0) {
                                    lemonToast.error('Cannot go live while test cases are failing')
                                    return
                                }
                                setFilterFormValue('mode', value)
                            }}
                        />
                    </div>

                    <EventFilterMetrics filterId={filterForm.id} />

                    <div className="space-y-2">
                        <div className="flex items-start justify-between">
                            <div>
                                <label className="font-semibold">Drop events matching</label>
                                <p className="text-muted text-sm mb-0">
                                    Build a filter expression. Drag conditions and groups to reorder or move between
                                    groups. Maximum {EVENT_FILTER_MAX_CONDITIONS} conditions and{' '}
                                    {EVENT_FILTER_MAX_DEPTH} levels of nesting. Empty groups are removed automatically
                                    on save.
                                </p>
                            </div>
                            <LemonButton size="small" type="secondary" onClick={() => setShowExpression(true)}>
                                Show expression
                            </LemonButton>
                        </div>
                        <DndContext
                            sensors={sensors}
                            collisionDetection={pointerWithin}
                            onDragStart={handleDragStart}
                            onDragEnd={handleDragEnd}
                        >
                            <div className="border rounded p-3">
                                <NodeEditor
                                    node={filterForm.filter_tree}
                                    path={[]}
                                    depth={0}
                                    showValidation={showFilterFormErrors}
                                />
                            </div>
                            {showFilterFormErrors && filterFormErrors.filter_tree && (
                                <div className="text-danger text-sm mt-1">{filterFormErrors.filter_tree}</div>
                            )}
                            <DragOverlay>
                                {activeNode ? (
                                    <div className="bg-bg-light border rounded px-3 py-1 shadow-md text-sm">
                                        {nodeSummary(activeNode)}
                                    </div>
                                ) : null}
                            </DragOverlay>
                        </DndContext>
                        <LemonModal
                            isOpen={showExpression}
                            onClose={() => setShowExpression(false)}
                            title="Filter expression"
                            description="Events matching this expression will be dropped."
                        >
                            <pre className="font-mono text-sm whitespace-pre-wrap p-3 border rounded bg-bg-light overflow-auto max-h-96">
                                {isTreeEmpty(filterForm.filter_tree)
                                    ? '(no conditions configured)'
                                    : `DROP WHERE\n  ${filterTreeToExpression(filterForm.filter_tree, 1).trim()}`}
                            </pre>
                        </LemonModal>
                    </div>

                    <LemonDivider />

                    <EventFilterTestCases />

                    <LemonDivider />

                    {!allTestsPass && filterForm.mode === 'live' && (
                        <div className="text-danger text-sm">
                            Some test cases are failing. The filter cannot go live until all tests pass. You can save
                            with tests failing, but the filter will be saved in dry run mode.
                        </div>
                    )}

                    <div className="flex gap-2">
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                if (filterForm.mode === 'live' && !allTestsPass) {
                                    setFilterFormValue('mode', 'dry_run')
                                }
                                submitFilterForm()
                            }}
                            loading={isFilterFormSubmitting}
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </SceneContent>
    )
}
