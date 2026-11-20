import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { IconX } from '@posthog/icons'
import { Button, Text, cn } from '@posthog/quill'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import type { AccountPropertyConfiguratorItemProps } from './AccountPropertyConfiguratorItem'
import { ACCOUNT_PROPERTY_KIND_LABELS } from './accountPropertyTypes'

export function QuillAccountPropertyConfiguratorItem({
    option,
    disabled = false,
    onRemove,
}: AccountPropertyConfiguratorItemProps): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({
        id: option.key,
        disabled,
    })

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            className={cn(
                'flex items-center gap-2 rounded-md border border-border bg-card px-2 py-1',
                isDragging && 'opacity-50'
            )}
            data-attr="account-pinned-property-row"
        >
            <button
                type="button"
                className={cn(
                    'flex items-center text-muted-foreground',
                    disabled ? 'cursor-not-allowed' : 'cursor-grab active:cursor-grabbing'
                )}
                aria-label={`Reorder ${option.label}`}
                disabled={disabled}
                {...attributes}
                {...listeners}
            >
                <SortableDragIcon />
            </button>
            <Text size="xs" render={<span className="m-0 min-w-0 flex-1 truncate font-medium" />}>
                {option.label}
            </Text>
            <Text size="xs" variant="muted" render={<span className="m-0 shrink-0" />}>
                {ACCOUNT_PROPERTY_KIND_LABELS[option.kind]}
            </Text>
            <Button
                size="icon-xs"
                tooltip={`Remove ${option.label}`}
                aria-label={`Remove ${option.label}`}
                onClick={onRemove}
                disabledReason={disabled ? 'Saving' : undefined}
            >
                <IconX />
            </Button>
        </div>
    )
}
