import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import type { AccountViewComponentInstance } from './accountViewDocument'

interface AccountViewEditorComponentItemProps {
    component: AccountViewComponentInstance
    label: string
    disabled: boolean
    onSpanChange: (span: number) => void
    onDuplicate: () => void
    onRemove: () => void
}

export function AccountViewEditorComponentItem({
    component,
    label,
    disabled,
    onSpanChange,
    onDuplicate,
    onRemove,
}: AccountViewEditorComponentItemProps): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({
        id: component.nodeId,
        disabled,
    })

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            className={`flex flex-wrap items-center gap-2 rounded border bg-surface-primary p-2 ${
                isDragging ? 'opacity-50' : ''
            }`}
            data-attr="account-view-editor-component"
        >
            <button
                type="button"
                className={`flex items-center text-secondary ${
                    disabled ? 'cursor-not-allowed' : 'cursor-grab active:cursor-grabbing'
                }`}
                aria-label={`Reorder ${label}`}
                disabled={disabled}
                {...attributes}
                {...listeners}
            >
                <SortableDragIcon />
            </button>
            <span className="min-w-32 flex-1 font-medium">{label}</span>
            <LemonSegmentedButton
                value={component.span === 6 ? 6 : 12}
                onChange={onSpanChange}
                options={[
                    { value: 6, label: 'Half' },
                    { value: 12, label: 'Full' },
                ]}
                size="xsmall"
                disabledReason={disabled ? 'Saving changes' : undefined}
            />
            <div className="flex items-center gap-1">
                <LemonButton
                    size="xsmall"
                    icon={<IconCopy />}
                    aria-label={`Duplicate ${label}`}
                    onClick={onDuplicate}
                    disabledReason={disabled ? 'Saving changes' : undefined}
                />
                <LemonButton
                    size="xsmall"
                    status="danger"
                    icon={<IconTrash />}
                    aria-label={`Remove ${label}`}
                    onClick={onRemove}
                    disabledReason={disabled ? 'Saving changes' : undefined}
                />
            </div>
        </div>
    )
}
