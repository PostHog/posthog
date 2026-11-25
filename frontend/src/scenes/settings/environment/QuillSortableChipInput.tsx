import {
    DndContext,
    DragEndEvent,
    KeyboardSensor,
    PointerSensor,
    closestCenter,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import {
    SortableContext,
    arrayMove,
    rectSortingStrategy,
    sortableKeyboardCoordinates,
    useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useState } from 'react'

import { Button, Chip, ChipClose, Input, cn } from '@posthog/quill'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

export interface QuillSortableChipInputProps {
    id?: string
    value: string[]
    onChange: (value: string[]) => void
    placeholder?: string
    limit?: number
    /** Disables adding, removing and reordering, and says why. */
    disabledReason?: string | null
    dataAttr?: string
}

/** A list of free-text values shown as chips the person can drag into order, with an input to add more. */
export function QuillSortableChipInput({
    id,
    value,
    onChange,
    placeholder,
    limit,
    disabledReason,
    dataAttr,
}: QuillSortableChipInputProps): JSX.Element {
    const [draft, setDraft] = useState('')
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )

    const trimmedDraft = draft.trim()
    const limitReached = limit !== undefined && value.length >= limit
    const inputDisabledReason =
        disabledReason || (limitReached ? `Remove a value to add another. The limit is ${limit}.` : undefined)
    const canReorder = !disabledReason && value.length > 1

    const addDraft = (): void => {
        if (!trimmedDraft || inputDisabledReason) {
            return
        }

        if (!value.includes(trimmedDraft)) {
            onChange([...value, trimmedDraft])
        }

        setDraft('')
    }

    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }

        onChange(arrayMove(value, value.indexOf(String(active.id)), value.indexOf(String(over.id))))
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2">
                <Input
                    id={id}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                            event.preventDefault()
                            addDraft()
                        }
                    }}
                    placeholder={placeholder}
                    disabledReason={inputDisabledReason}
                    data-attr={dataAttr}
                    className="min-w-0 flex-1"
                />
                <Button
                    variant="outline"
                    onClick={addDraft}
                    disabledReason={inputDisabledReason ?? (!trimmedDraft ? 'Type a value to add' : undefined)}
                >
                    Add
                </Button>
            </div>
            {value.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                        <SortableContext items={value} strategy={rectSortingStrategy}>
                            {value.map((item) => (
                                <QuillSortableChip
                                    key={item}
                                    value={item}
                                    reorderable={canReorder}
                                    disabledReason={disabledReason}
                                    onRemove={() => onChange(value.filter((other) => other !== item))}
                                />
                            ))}
                        </SortableContext>
                    </DndContext>
                    <Button variant="link-muted" size="sm" onClick={() => onChange([])} disabledReason={disabledReason}>
                        Clear all
                    </Button>
                </div>
            )}
        </div>
    )
}

function QuillSortableChip({
    value,
    reorderable,
    disabledReason,
    onRemove,
}: {
    value: string
    reorderable: boolean
    disabledReason?: string | null
    onRemove: () => void
}): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: value,
        disabled: !reorderable,
    })

    return (
        <Chip
            ref={setNodeRef}
            style={{ transform: CSS.Translate.toString(transform), transition }}
            className={cn('max-w-full', isDragging && 'z-10 opacity-50')}
        >
            {reorderable && (
                <Button
                    size="icon-xs"
                    aria-label={`Drag ${value} to reorder`}
                    className="cursor-grab active:cursor-grabbing"
                    {...attributes}
                    {...listeners}
                >
                    <SortableDragIcon />
                </Button>
            )}
            <span className="truncate" title={value}>
                {value}
            </span>
            <ChipClose aria-label={`Remove ${value}`} disabledReason={disabledReason} onClick={onRemove} />
        </Chip>
    )
}
