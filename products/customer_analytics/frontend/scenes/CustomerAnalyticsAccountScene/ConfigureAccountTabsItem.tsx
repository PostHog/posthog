import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import { AccountTabLabel } from './AccountTabLabel'
import type { AccountTabDefinition } from './accountTabs'

interface ConfigureAccountTabsItemProps {
    tab: AccountTabDefinition
    visible: boolean
    disabledReason: string | undefined
    onVisibilityChange: (visible: boolean) => void
}

export function ConfigureAccountTabsItem({
    tab,
    visible,
    disabledReason,
    onVisibilityChange,
}: ConfigureAccountTabsItemProps): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({
        id: tab.id,
        disabled: !!disabledReason,
    })

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            className={`flex items-center gap-2 rounded border bg-surface-primary p-2 ${isDragging ? 'opacity-50' : ''}`}
            data-attr="account-tabs-item"
        >
            <button
                type="button"
                className={`flex items-center text-secondary ${
                    disabledReason ? 'cursor-not-allowed' : 'cursor-grab active:cursor-grabbing'
                }`}
                aria-label={`Reorder ${tab.label}`}
                disabled={!!disabledReason}
                {...attributes}
                {...listeners}
            >
                <SortableDragIcon />
            </button>
            <LemonCheckbox
                checked={visible}
                onChange={onVisibilityChange}
                disabledReason={disabledReason}
                label={<AccountTabLabel tab={tab} />}
                className="min-w-0 flex-1"
            />
        </div>
    )
}
