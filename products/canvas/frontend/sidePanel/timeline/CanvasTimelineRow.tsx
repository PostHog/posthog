import { ReactNode } from 'react'

import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, cn } from '@posthog/quill'

export interface CanvasTimelineRowProps {
    title: string
    meta: string
    icon: ReactNode
    /** Status badges, such as Live or a build that failed. */
    badges?: ReactNode
    /** Whether this row's version is the one on screen. */
    viewing: boolean
    onOpen: () => void
    action?: ReactNode
    dataAttr: string
}

/** One entry on the timeline. Selecting the row shows that version in the canvas. */
export function CanvasTimelineRow({
    title,
    meta,
    icon,
    badges,
    viewing,
    onOpen,
    action,
    dataAttr,
}: CanvasTimelineRowProps): JSX.Element {
    return (
        <Item
            variant="outline"
            size="xs"
            data-selected={viewing || undefined}
            // The open button stretches over the whole row, so the row is one target and the action stays separate.
            // The app compiles fill tokens as plain classes only, so the selected fill is toggled, not a variant.
            className={cn('relative items-start', viewing && 'bg-fill-selected')}
            // Item drops a role prop, so the listitem role for ItemGroup's list rides on the render element.
            render={<div role="listitem" />}
        >
            <ItemMedia variant="icon" aria-hidden>
                {icon}
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="min-w-0">
                    <button
                        type="button"
                        className="line-clamp-2 cursor-pointer text-left outline-none after:absolute after:inset-0 after:rounded-sm focus-visible:after:ring-2 focus-visible:after:ring-ring"
                        onClick={onOpen}
                        aria-current={viewing || undefined}
                        data-attr={dataAttr}
                    >
                        {title}
                    </button>
                </ItemTitle>
                <ItemDescription className="truncate">{meta}</ItemDescription>
                {badges && <div className="flex flex-wrap items-center gap-1">{badges}</div>}
            </ItemContent>
            {action && <ItemActions className="relative z-10">{action}</ItemActions>}
        </Item>
    )
}
