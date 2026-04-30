/**
 * Shared header for popover sub-pages. Renders a back button (← chevron)
 * + title. The back button calls `onBack` — the parent state machine
 * decides what "back" means for the current page (typically: re-open the
 * dropdown menu).
 */
import { ChevronLeftIcon } from 'lucide-react'

import { Button, cn } from '@posthog/quill'

export interface MenuFilterHeaderProps {
    title: string
    onBack: () => void
    className?: string
}

export function MenuFilterHeader({ title, onBack, className }: MenuFilterHeaderProps): JSX.Element {
    return (
        <div
            className={cn('flex items-center gap-2 px-3 py-2 border-b text-sm font-semibold shrink-0', className)}
            data-slot="menu-filter-header"
        >
            <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="Back"
                onClick={onBack}
                className="-ml-1 shrink-0"
                data-attr="menu-filter-back"
            >
                <ChevronLeftIcon className="size-4" />
            </Button>
            <span className="flex-1 truncate">{title}</span>
        </div>
    )
}
