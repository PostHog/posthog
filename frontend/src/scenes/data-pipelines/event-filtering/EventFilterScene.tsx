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
import { useCallback, useMemo, useRef, useState } from 'react'

import { LemonBanner, LemonButton, LemonDivider, LemonLabel, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { eventFilterLogic, EVENT_FILTER_MAX_CONDITIONS, EVENT_FILTER_MAX_DEPTH } from './eventFilterLogic'
import { EventFilterMetrics } from './EventFilterMetrics'
import { EventFilterTestCases } from './EventFilterTestCases'
import { NodeEditor } from './EventFilterTreeEditor'
import { filterTreeToExpression, isTreeEmpty, nodeSummary } from './filterTreeDisplay'
import { moveBetweenGroups, reorderWithinGroup, resolveDropTarget } from './filterTreeDnd'
import { getNodeAtPath, isAncestorPath, splitParentChild } from './filterTreePath'
import { NodeIdMap } from './NodeIdMap'

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
    const nodeIds = useRef(new NodeIdMap()).current

    // Build nid → path index on every render (also assigns IDs to new nodes)
    useMemo(() => nodeIds.buildIndex(filterForm.filter_tree), [filterForm.filter_tree, nodeIds])

    const sensors = useSensors(
        useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
        useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } })
    )

    const handleDragStart = useCallback((event: DragStartEvent) => {
        setActiveId(String(event.active.id))
    }, [])

    const handleDragEnd = useCallback(
        (event: DragEndEvent) => {
            setActiveId(null)
            const { active, over } = event
            if (!over || active.id === over.id) {
                return
            }

            const overIdStr = String(over.id)
            const tree = filterForm.filter_tree
            nodeIds.buildIndex(tree)

            const activePath = nodeIds.pathOf(String(active.id))
            if (!activePath) {
                return
            }
            const activeParent = splitParentChild(activePath)
            if (!activeParent) {
                return
            }

            const target = resolveDropTarget(overIdStr, tree, nodeIds)
            if (!target) {
                return
            }
            if (isAncestorPath(activePath, target.groupPath)) {
                return
            }

            const sameGroup = activeParent.parentPath.join('.') === target.groupPath.join('.')

            if (sameGroup) {
                const reorderedGroup = reorderWithinGroup(
                    tree,
                    activeParent.parentPath,
                    activeParent.childIndex,
                    target.insertIndex,
                    arrayMove
                )
                if (reorderedGroup) {
                    updateTreeNode(activeParent.parentPath, reorderedGroup)
                }
            } else {
                const destGroup = target.groupPath.length === 0 ? tree : getNodeAtPath(tree, target.groupPath)
                if (!destGroup) {
                    return
                }
                const destGroupNid = nodeIds.nidOf(destGroup)
                const newTree = moveBetweenGroups(
                    tree,
                    activeParent.parentPath,
                    activeParent.childIndex,
                    destGroupNid,
                    target.insertIndex,
                    nodeIds
                )
                if (newTree) {
                    setFilterFormValue('filter_tree', newTree)
                }
            }
        },
        [filterForm.filter_tree, updateTreeNode, setFilterFormValue]
    )

    const activeNode = activeId ? getNodeAtPath(filterForm.filter_tree, nodeIds.pathOf(activeId) ?? []) : null

    return (
        <SceneContent>
            <SceneTitleSection
                name="Event ingestion filtering"
                description="Drop events at ingestion time based on event name or distinct ID."
                resourceType={{ type: 'data_pipeline' }}
            />
            <Form logic={eventFilterLogic} formKey="filterForm" enableFormOnSubmit>
                <div className="space-y-4">
                    <LemonBanner type="info">
                        <p className="mb-1">
                            Event ingestion filtering is the most efficient way to drop unwanted events. Filters are
                            evaluated early in the ingestion pipeline, before transformations run.
                        </p>
                        <p className="mb-0">
                            Events that pass these filters will still go through any active{' '}
                            <strong>transformations</strong>, which can also drop or modify events. Use event filters
                            for simple drop rules based on event name or distinct ID, and only use transformations when
                            you need more complex logic.
                        </p>
                    </LemonBanner>

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
                        <LemonSegmentedButton
                            size="small"
                            options={[
                                { value: 'disabled', label: 'Disabled' },
                                { value: 'dry_run', label: 'Dry run' },
                                {
                                    value: 'live',
                                    label: 'Live',
                                    disabledReason:
                                        !allTestsPass && filterForm.test_cases.length > 0
                                            ? 'All test cases must pass before going live'
                                            : undefined,
                                },
                            ]}
                            value={filterForm.mode}
                            onChange={(value) => setFilterFormValue('mode', value)}
                        />
                    </div>

                    <EventFilterMetrics filterId={filterForm.id} />

                    <div className="space-y-2">
                        <div className="flex items-start justify-between">
                            <div>
                                <LemonLabel>Drop events matching</LemonLabel>
                                <p className="text-muted text-sm mb-0">
                                    Build a filter expression. Drag conditions and groups to reorder or move between
                                    groups. Maximum {EVENT_FILTER_MAX_CONDITIONS} conditions and{' '}
                                    {EVENT_FILTER_MAX_DEPTH} levels of nesting. Empty groups are removed automatically
                                    on save.
                                </p>
                            </div>
                            <LemonButton
                                size="small"
                                type="secondary"
                                className="ml-2 shrink-0"
                                onClick={() => setShowExpression(true)}
                            >
                                Show as ASCII
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
                                    nodeIds={nodeIds}
                                />
                            </div>
                            {showFilterFormErrors && filterFormErrors.mode && (
                                <LemonBanner type="error">{filterFormErrors.mode}</LemonBanner>
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
                            title="Filter tree"
                            description="Events matching this expression will be dropped."
                        >
                            <pre className="font-mono text-sm whitespace-pre-wrap p-3 border rounded bg-bg-light overflow-auto max-h-96">
                                {isTreeEmpty(filterForm.filter_tree)
                                    ? '(no conditions configured)'
                                    : filterTreeToExpression(filterForm.filter_tree)}
                            </pre>
                        </LemonModal>
                    </div>

                    <LemonDivider />

                    <EventFilterTestCases />

                    <LemonDivider />

                    {!allTestsPass && filterForm.mode === 'live' && (
                        <LemonBanner type="warning">
                            Some test cases are failing. The filter cannot go live until all tests pass. You can save
                            with tests failing, but the filter will be saved in dry run mode.
                        </LemonBanner>
                    )}

                    <div className="flex gap-2">
                        <LemonButton type="primary" onClick={() => submitFilterForm()} loading={isFilterFormSubmitting}>
                            Save
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </SceneContent>
    )
}
