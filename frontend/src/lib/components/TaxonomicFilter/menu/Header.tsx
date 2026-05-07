/**
 * Shared header for popover sub-pages. Renders a back button (← chevron)
 * + title. The back button calls `onBack` — the parent state machine
 * decides what "back" means for the current page (typically: re-open the
 * dropdown menu).
 */
import { ChevronLeftIcon } from 'lucide-react'

import { Button, cn, Kbd } from '@posthog/quill'

export interface MenuFilterHeaderProps {
    title: string
    onBack: () => void
    className?: string
    /**
     * Whether the Tab keyboard hint should render. Drilled views (single
     * category, Recent, Pinned) have no chip row to cycle through, so
     * the hint is misleading there — pass `false` to suppress it.
     * Defaults to `true` so the All / mixed-group view keeps the hint.
     */
    showTabHint?: boolean
}

export function MenuFilterHeader({ title, onBack, className, showTabHint = true }: MenuFilterHeaderProps): JSX.Element {
    return (
        <div
            className={cn('flex items-center gap-2 px-3 py-2 border-b text-sm font-semibold shrink-0', className)}
            data-slot="menu-filter-header"
        >
            <Button
                type="button"
                variant="outline"
                size="icon-sm"
                aria-label="Back"
                onClick={onBack}
                className="-ml-1 shrink-0"
                data-attr="menu-filter-back"
            >
                <ChevronLeftIcon className="size-4" />
            </Button>
            <span className="flex-1 truncate">{title}</span>

            <div className="items-center gap-2 text-xs hidden @[720px]/main-content-container:flex">
                {showTabHint && (
                    <>
                        <Kbd>Tab</Kbd>{' '}
                        <span className="text-muted-foreground font-normal">Cycle through categories</span>
                    </>
                )}
                <Kbd>Esc</Kbd> <span className="text-muted-foreground font-normal">Go back one level</span>
            </div>
        </div>
    )
}
