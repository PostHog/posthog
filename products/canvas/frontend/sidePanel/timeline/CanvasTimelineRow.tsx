import { ReactNode } from 'react'

import { Text } from '@posthog/quill'

export interface CanvasTimelineRowProps {
    title: string
    meta: string
    icon?: ReactNode
    badges: ReactNode
    /** Whether this row's version is the one on screen. */
    viewing: boolean
    onOpen: () => void
    action: ReactNode
    dataAttr: string
}

/** One entry on the timeline: opening it shows that version in the canvas. */
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
        <li
            data-selected={viewing || undefined}
            className="group flex min-w-0 items-start gap-2 rounded-md px-2 py-1.5 hover:bg-fill-hover data-selected:bg-fill-selected"
        >
            <button
                type="button"
                className="flex min-w-0 flex-1 cursor-pointer flex-col gap-1 text-left"
                onClick={onOpen}
                aria-current={viewing || undefined}
                data-attr={dataAttr}
            >
                <span className="flex min-w-0 items-center gap-1.5">
                    {icon && <span className="flex shrink-0 text-muted-foreground">{icon}</span>}
                    <Text size="xs" weight="medium" className="line-clamp-2 min-w-0">
                        {title}
                    </Text>
                </span>
                <Text size="xxs" variant="muted" className="truncate">
                    {meta}
                </Text>
                <span className="flex flex-wrap items-center gap-1">{badges}</span>
            </button>
            {action && <div className="shrink-0">{action}</div>}
        </li>
    )
}
