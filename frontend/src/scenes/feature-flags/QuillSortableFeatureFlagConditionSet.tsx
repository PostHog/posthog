import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { Button } from '@posthog/quill'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import { QuillFeatureFlagConditionSet, QuillFeatureFlagConditionSetProps } from './QuillFeatureFlagConditionSet'

export function QuillSortableFeatureFlagConditionSet(
    props: Omit<QuillFeatureFlagConditionSetProps, 'sortable'>
): JSX.Element {
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id: props.group.sort_key,
    })

    return (
        <QuillFeatureFlagConditionSet
            {...props}
            sortable={{
                setNodeRef,
                style: {
                    transform: CSS.Transform.toString(transform),
                    transition: isDragging ? undefined : transition,
                },
                isDragging,
                dragHandle:
                    props.totalGroups > 1 ? (
                        <Button
                            ref={setActivatorNodeRef}
                            size="icon-sm"
                            aria-label="Reorder condition"
                            tooltip="Drag to reorder conditions"
                            className="cursor-grab active:cursor-grabbing"
                            {...listeners}
                            {...attributes}
                            data-attr="feature-flag-condition-drag-handle"
                        >
                            <SortableDragIcon />
                        </Button>
                    ) : null,
            }}
        />
    )
}
