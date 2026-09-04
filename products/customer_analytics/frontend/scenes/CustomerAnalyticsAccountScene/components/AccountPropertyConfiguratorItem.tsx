import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import type { AccountPropertyOption } from './accountPropertyTypes'

export interface AccountPropertyConfiguratorItemProps {
    option: AccountPropertyOption
    onRemove: () => void
}

export function AccountPropertyConfiguratorItem({
    option,
    onRemove,
}: AccountPropertyConfiguratorItemProps): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({ id: option.key })

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            className={`flex items-center gap-2 rounded border bg-surface-primary px-2 py-1.5 ${
                isDragging ? 'opacity-50' : ''
            }`}
            data-attr="account-pinned-property-row"
        >
            <button
                type="button"
                className="flex cursor-grab items-center text-secondary active:cursor-grabbing"
                aria-label={`Reorder ${option.label}`}
                {...attributes}
                {...listeners}
            >
                <SortableDragIcon />
            </button>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{option.label}</span>
            <span className="shrink-0 text-xs text-secondary">
                {option.kind === 'custom' ? 'Custom property' : 'Relationship'}
            </span>
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                tooltip={`Remove ${option.label}`}
                aria-label={`Remove ${option.label}`}
                onClick={onRemove}
            />
        </div>
    )
}
