import { useDroppable, useDndMonitor } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { IconDragHandle } from 'lib/lemon-ui/icons'

import {
    EVENT_FILTER_MAX_CONDITIONS,
    EVENT_FILTER_MAX_DEPTH,
    eventFilterLogic,
    FilterNode,
    TreePath,
} from './eventFilterLogic'
import { NodeIdMap } from './NodeIdMap'

const FIELD_OPTIONS = [
    { value: 'event_name', label: 'Event name' },
    { value: 'distinct_id', label: 'Distinct ID' },
]

const OPERATOR_OPTIONS = [
    { value: 'exact', label: 'equals' },
    { value: 'contains', label: 'contains' },
]

export function SortableItem({ id, children }: { id: string; children: React.ReactNode }): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.3 : 1,
    }
    return (
        <div ref={setNodeRef} style={style} className="flex items-start gap-1">
            <div className="mt-2 cursor-grab text-muted hover:text-default shrink-0" {...attributes} {...listeners}>
                <IconDragHandle />
            </div>
            <div className="flex-1 min-w-0">{children}</div>
        </div>
    )
}

function ConditionEditor({
    node,
    path,
    onDelete,
    showValidation,
}: {
    node: FilterNode & { type: 'condition' }
    path: TreePath
    onDelete?: () => void
    showValidation?: boolean
}): JSX.Element {
    const { updateTreeNode } = useActions(eventFilterLogic)
    const isEmpty = showValidation && (!node.value || node.value.trim() === '')
    return (
        <div className="flex items-center gap-2 py-1">
            <LemonSelect
                size="small"
                options={FIELD_OPTIONS}
                value={node.field}
                onChange={(value) => updateTreeNode(path, { ...node, field: value as typeof node.field })}
            />
            <LemonSelect
                size="small"
                options={OPERATOR_OPTIONS}
                value={node.operator}
                onChange={(value) => updateTreeNode(path, { ...node, operator: value as typeof node.operator })}
            />
            <LemonInput
                size="small"
                value={node.value}
                onChange={(value) => updateTreeNode(path, { ...node, value })}
                placeholder="Value..."
                className="flex-1"
                status={isEmpty ? 'danger' : undefined}
            />
            {onDelete && (
                <LemonButton
                    icon={<IconTrash />}
                    size="xsmall"
                    status="danger"
                    onClick={onDelete}
                    tooltip="Remove"
                    aria-label="Remove"
                    data-attr={`remove-${path.length === 0 ? 'root' : path.join('-')}`}
                />
            )}
        </div>
    )
}

function GroupEditor({
    node,
    path,
    depth,
    onDelete,
    showValidation,
    nodeIds,
}: {
    node: FilterNode & { type: 'and' | 'or' }
    path: TreePath
    depth: number
    onDelete?: () => void
    showValidation?: boolean
    nodeIds: NodeIdMap
}): JSX.Element {
    const { updateTreeNode, removeChild, wrapInNot, addChild } = useActions(eventFilterLogic)
    const { conditionCount } = useValues(eventFilterLogic)

    // A new condition adds a leaf at depth+1; a new group adds itself at depth+1
    // with a leaf at depth+2. Both must satisfy the backend's max_depth ≤ N rule.
    const maxConditionsReason =
        conditionCount >= EVENT_FILTER_MAX_CONDITIONS
            ? `Maximum of ${EVENT_FILTER_MAX_CONDITIONS} conditions reached`
            : undefined
    const maxDepthReason = `Maximum nesting depth of ${EVENT_FILTER_MAX_DEPTH} reached`
    const addConditionDisabledReason =
        maxConditionsReason ?? (depth >= EVENT_FILTER_MAX_DEPTH ? maxDepthReason : undefined)
    const addGroupDisabledReason =
        maxConditionsReason ?? (depth >= EVENT_FILTER_MAX_DEPTH - 1 ? maxDepthReason : undefined)

    const pathAttr = path.length === 0 ? 'root' : path.join('-')
    const droppableId = `drop:${nodeIds.nidOf(node)}`
    const { setNodeRef, isOver } = useDroppable({ id: droppableId })
    const borderColor = node.type === 'and' ? 'bg-[#2563EB]' : 'bg-[#F59E0B]'

    const childNids = node.children.map((child) => nodeIds.nidOf(child))

    // Track whether the drag is over this group's droppable zone or any
    // of its direct children (including items dragged from other groups).
    // useDndMonitor fires on ALL groups simultaneously, so each group checks
    // if the over target belongs to it and only updates its own state.
    const [isOverGroup, setIsOverGroup] = useState(false)
    useDndMonitor({
        onDragOver(event) {
            const overId = event.over ? String(event.over.id) : undefined
            const isMatch = overId === droppableId || (!!overId && childNids.includes(overId))
            setIsOverGroup(isMatch)
        },
        onDragEnd() {
            setIsOverGroup(false)
        },
        onDragCancel() {
            setIsOverGroup(false)
        },
    })

    const shouldHighlight = isOver || isOverGroup

    return (
        <div ref={setNodeRef} className={`flex gap-0 ${shouldHighlight ? 'bg-fill-highlight rounded' : ''}`}>
            <div className={`w-0.5 shrink-0 rounded ${borderColor}`} />
            <div className="flex-1 min-w-0 py-1 pl-2 space-y-1">
                <div className="flex items-center gap-2">
                    <LemonSelect
                        size="xsmall"
                        options={[
                            { value: 'and', label: 'AND' },
                            { value: 'or', label: 'OR' },
                        ]}
                        value={node.type}
                        onChange={(value) =>
                            updateTreeNode(path, { type: value as 'and' | 'or', children: node.children })
                        }
                    />
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        data-attr={`negate-${pathAttr}`}
                        onClick={() => wrapInNot(path)}
                    >
                        Negate
                    </LemonButton>
                    {onDelete && (
                        <LemonButton
                            icon={<IconTrash />}
                            size="xsmall"
                            status="danger"
                            onClick={onDelete}
                            tooltip="Remove"
                            aria-label="Remove"
                            data-attr={`remove-${pathAttr}`}
                        />
                    )}
                </div>

                <SortableContext items={childNids} strategy={verticalListSortingStrategy}>
                    {node.children.map((child, i) => {
                        const childPath: TreePath = [...path, i]
                        const childId = nodeIds.nidOf(child)
                        return (
                            <SortableItem key={childId} id={childId}>
                                <NodeEditor
                                    node={child}
                                    path={childPath}
                                    depth={depth + 1}
                                    onDelete={() => removeChild(path, i)}
                                    showValidation={showValidation}
                                    nodeIds={nodeIds}
                                />
                            </SortableItem>
                        )
                    })}
                </SortableContext>

                <div className="flex gap-2">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPlusSmall />}
                        data-attr={`add-condition-${pathAttr}`}
                        onClick={() => addChild(path)}
                        disabledReason={addConditionDisabledReason}
                    >
                        Add condition
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPlusSmall />}
                        data-attr={`add-group-${pathAttr}`}
                        onClick={() => {
                            const newGroup: FilterNode = {
                                type: 'and',
                                children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: '' }],
                            }
                            updateTreeNode(path, { ...node, children: [...node.children, newGroup] })
                        }}
                        disabledReason={addGroupDisabledReason}
                    >
                        Add group
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

export function NodeEditor({
    node,
    path,
    depth,
    onDelete,
    showValidation,
    nodeIds,
}: {
    node: FilterNode
    path: TreePath
    depth: number
    onDelete?: () => void
    showValidation?: boolean
    nodeIds: NodeIdMap
}): JSX.Element {
    const { unwrapNot } = useActions(eventFilterLogic)

    if (node.type === 'condition') {
        return <ConditionEditor node={node} path={path} onDelete={onDelete} showValidation={showValidation} />
    }
    if (node.type === 'not') {
        return (
            <div className="border-l-2 border-danger pl-3 py-1 space-y-1">
                <div className="flex items-center gap-2">
                    <span className="text-danger font-semibold text-xs">NOT</span>
                    <LemonButton size="xsmall" status="danger" onClick={() => unwrapNot(path)}>
                        Remove NOT
                    </LemonButton>
                    {onDelete && (
                        <LemonButton
                            icon={<IconTrash />}
                            size="xsmall"
                            status="danger"
                            onClick={onDelete}
                            tooltip="Remove"
                        />
                    )}
                </div>
                <NodeEditor
                    node={node.child}
                    path={[...path, 'child']}
                    depth={depth + 1}
                    showValidation={showValidation}
                    nodeIds={nodeIds}
                />
            </div>
        )
    }
    return (
        <GroupEditor
            node={node}
            path={path}
            depth={depth}
            onDelete={onDelete}
            showValidation={showValidation}
            nodeIds={nodeIds}
        />
    )
}
