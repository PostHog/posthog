import {
    DndContext,
    DragEndEvent,
    KeyboardSensor,
    PointerSensor,
    closestCenter,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import {
    SortableContext,
    arrayMove,
    sortableKeyboardCoordinates,
    useSortable,
    verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import { DEFAULT_RESPONSE_TARGET_GROUPS, ResponseTargetGroup } from '../tickets/responseTargets'
import { supportSettingsLogic } from './supportSettingsLogic'

interface SortableGroupRowProps {
    id: string
    group: ResponseTargetGroup
    onPatch: (patch: Partial<ResponseTargetGroup>) => void
    onRemove: () => void
}

function SortableGroupRow({ id, group, onPatch, onRemove }: SortableGroupRowProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })

    return (
        <div
            ref={setNodeRef}
            style={{
                transform: CSS.Transform.toString(transform),
                transition: isDragging ? 'none' : transition,
                opacity: isDragging ? 0.8 : 1,
                zIndex: isDragging ? 1000 : 'auto',
                position: 'relative',
            }}
            className="flex items-center gap-2"
        >
            <div
                className="flex items-center justify-center cursor-grab active:cursor-grabbing px-1"
                {...attributes}
                {...listeners}
            >
                <SortableDragIcon className="text-muted-alt" />
            </div>
            <LemonInput
                value={group.label}
                onChange={(label) => onPatch({ label })}
                placeholder="Group label"
                className="w-60 shrink-0"
            />
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                value={group.tags}
                onChange={(tags) => onPatch({ tags })}
                placeholder="Ticket tags (exact match)"
                className="flex-1"
                data-attr="response-target-group-tags"
            />
            <LemonButton icon={<IconTrash />} size="small" tooltip="Remove group" onClick={onRemove} />
        </div>
    )
}

export function ResponseTargetsSection(): JSX.Element {
    const {
        responseTargetGroupsView,
        responseTargetGroupsDraft,
        responseTargetGroupsCustomized,
        responseTargetGroupsError,
        currentTeamLoading,
    } = useValues(supportSettingsLogic)
    const { setResponseTargetGroupsDraft, saveResponseTargetGroups } = useActions(supportSettingsLogic)

    const groups = responseTargetGroupsView
    const dirty = responseTargetGroupsDraft !== null

    // Stable per-row ids for drag-and-drop and React keys, so a row's
    // transient input state travels with the row when the list reorders.
    // Mutations below keep this array position-aligned with `groups`; while
    // pristine it just mirrors the saved ladder.
    const [rowIds, setRowIds] = useState<string[]>(() => groups.map((_, index) => `row-${index}`))
    const nextIdRef = useRef(groups.length)
    useEffect(() => {
        if (!dirty) {
            setRowIds(groups.map((_, index) => `row-${index}`))
            nextIdRef.current = groups.length
        }
    }, [dirty, groups])
    const ids = rowIds.length === groups.length ? rowIds : groups.map((_, index) => `row-${index}`)

    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )

    const patchGroup = (index: number, patch: Partial<ResponseTargetGroup>): void =>
        setResponseTargetGroupsDraft(groups.map((group, i) => (i === index ? { ...group, ...patch } : group)))
    const removeGroup = (index: number): void => {
        setRowIds(ids.filter((_, i) => i !== index))
        setResponseTargetGroupsDraft(groups.filter((_, i) => i !== index))
    }
    const addGroup = (): void => {
        setRowIds([...ids, `row-new-${nextIdRef.current++}`])
        setResponseTargetGroupsDraft([...groups, { label: '', tags: [] }])
    }
    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (over && active.id !== over.id) {
            const oldIndex = ids.indexOf(String(active.id))
            const newIndex = ids.indexOf(String(over.id))
            if (oldIndex !== -1 && newIndex !== -1) {
                setRowIds(arrayMove(ids, oldIndex, newIndex))
                setResponseTargetGroupsDraft(arrayMove(groups, oldIndex, newIndex))
            }
        }
    }

    return (
        <div className="flex flex-col gap-4 max-w-[800px]">
            <ul className="list-disc pl-4 flex flex-col gap-1">
                <li>
                    When sorting tickets by <strong>Response target</strong>, it orders tickets by the groups you define
                    below, then by SLA within each group.
                </li>
                <li>Groups match on ticket tags (exact matches only).</li>
                <li>A ticket with several matching tags is shown in the highest group with a matching tag.</li>
                <li>Tickets with no matching tags land in the top group, so they won't be missed (for triage.)</li>
                <li>The starter groups are just examples, replace them with your own response targets and tags.</li>
            </ul>
            <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={handleDragEnd}
                modifiers={[restrictToVerticalAxis]}
            >
                <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                    <div className="flex flex-col gap-2">
                        {groups.map((group, index) => (
                            <SortableGroupRow
                                key={ids[index]}
                                id={ids[index]}
                                group={group}
                                onPatch={(patch) => patchGroup(index, patch)}
                                onRemove={() => removeGroup(index)}
                            />
                        ))}
                    </div>
                </SortableContext>
            </DndContext>
            {responseTargetGroupsError && <LemonBanner type="warning">{responseTargetGroupsError}</LemonBanner>}
            <div className="flex items-center gap-2">
                <LemonButton type="secondary" icon={<IconPlus />} onClick={addGroup}>
                    Add group
                </LemonButton>
                <LemonButton
                    type="primary"
                    loading={dirty && currentTeamLoading}
                    disabledReason={!dirty ? 'No unsaved changes' : (responseTargetGroupsError ?? undefined)}
                    onClick={() => saveResponseTargetGroups(responseTargetGroupsDraft)}
                >
                    Save groups
                </LemonButton>
                {dirty && (
                    <LemonButton type="tertiary" onClick={() => setResponseTargetGroupsDraft(null)}>
                        Discard changes
                    </LemonButton>
                )}
                {responseTargetGroupsCustomized && (
                    <LemonButton
                        type="tertiary"
                        status="danger"
                        onClick={() => setResponseTargetGroupsDraft([...DEFAULT_RESPONSE_TARGET_GROUPS])}
                        disabledReason={dirty ? 'Save or discard your changes first' : undefined}
                        tooltip="Replace the groups below with the example starter groups — nothing is erased until you save"
                    >
                        Reset to examples
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
