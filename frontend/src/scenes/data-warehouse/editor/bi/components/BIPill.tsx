import { forwardRef } from 'react'

import { IconChevronDown } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { BIShelf, BI_SHELF_PILL_DRAG_MIME_TYPE, BIShelfPillDragData } from '../biEditorTypes'

export type BIPillKind = 'dimension' | 'measure' | 'filter'

export interface BIPillProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
    kind: BIPillKind
    label: string
    detail?: string
    shelf: BIShelf
    index: number
    incomplete?: boolean
    /** Called when the pill is dropped outside every shelf, which removes it. */
    onDropOutside: () => void
}

/** A draggable field on a shelf. Blue for dimensions, green for measures, like desktop BI tools. */
export const BIPill = forwardRef<HTMLButtonElement, BIPillProps>(function BIPill(
    { kind, label, detail, shelf, index, incomplete, onDropOutside, className, ...buttonProps },
    ref
) {
    return (
        <button
            ref={ref}
            type="button"
            draggable
            onDragStart={(event) => {
                const dragData: BIShelfPillDragData = { shelf, index }
                event.dataTransfer.effectAllowed = 'move'
                event.dataTransfer.setData(BI_SHELF_PILL_DRAG_MIME_TYPE, JSON.stringify(dragData))
            }}
            onDragEnd={(event) => {
                if (event.dataTransfer.dropEffect === 'none') {
                    onDropOutside()
                }
            }}
            className={cn(
                'inline-flex h-6 max-w-72 shrink-0 cursor-grab items-center gap-1 rounded border px-2 text-xs font-semibold',
                'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent',
                incomplete
                    ? 'border-dashed border-primary bg-surface-primary text-secondary'
                    : kind === 'measure'
                      ? 'border-transparent bg-success text-white hover:opacity-90'
                      : kind === 'dimension'
                        ? 'border-transparent bg-brand-blue text-white hover:opacity-90'
                        : 'border-primary bg-surface-primary text-primary hover:bg-fill-highlight-100',
                className
            )}
            {...buttonProps}
        >
            <span className="truncate">{label}</span>
            {detail ? <span className="truncate font-normal opacity-80">{detail}</span> : null}
            <IconChevronDown className="shrink-0 opacity-70" />
        </button>
    )
})
