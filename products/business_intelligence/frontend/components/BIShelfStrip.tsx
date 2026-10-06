import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { BIShelf } from 'products/business_intelligence/frontend/biEditorTypes'
import { BIShelfDropTarget } from 'products/business_intelligence/frontend/components/BIShelfDropTarget'

/** A horizontal Rows or Columns shelf above the view. */
export function BIShelfStrip({
    shelf,
    title,
    icon,
    emptyText,
    children,
}: {
    shelf: Extract<BIShelf, 'rows' | 'columns'>
    title: string
    icon: ReactNode
    emptyText: string
    children: ReactNode[]
}): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { addBlankFieldToShelf } = useActions(biEditorLogic)

    return (
        <BIShelfDropTarget shelf={shelf} className="flex min-h-9 items-stretch rounded-none border-b">
            <div className="flex w-24 shrink-0 items-center gap-1.5 border-r px-2 text-xs font-semibold text-secondary">
                <span className="flex shrink-0">{icon}</span>
                {title}
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 px-1.5 py-1">
                {children.length > 0 ? children : <span className="px-1 text-xs text-tertiary">{emptyText}</span>}
                <LemonButton
                    icon={<IconPlus />}
                    size="xsmall"
                    type="tertiary"
                    className="ml-auto"
                    tooltip="Add a calculated field"
                    aria-label={`Add a calculated field to ${title.toLowerCase()}`}
                    disabledReason={!config.source ? 'Select a data source first' : undefined}
                    onClick={() => addBlankFieldToShelf(shelf)}
                    data-attr={`bi-editor-${shelf}-add-field`}
                />
            </div>
        </BIShelfDropTarget>
    )
}
