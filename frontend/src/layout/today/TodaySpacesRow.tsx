import { PreviewCard } from '@base-ui/react/preview-card'
import { useId } from 'react'

import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayPreviewPayload, todayPreviewCardHandle } from './todayPreviewCardHandle'

const PREVIEW_OPEN_DELAY_MS = 400
const PREVIEW_CLOSE_DELAY_MS = 100

interface TodaySpacesRowProps {
    label: string
    icon: JSX.Element
    to: string
    active: boolean
    dataAttr: string
    action?: JSX.Element | null
    /** Stays visible at the end of the row, after the hover action. */
    badge?: JSX.Element | null
    /** How many icon buttons `action` holds, so the label truncates before them. */
    actionCount?: 1 | 2
    /** What the hover card shows for this row. The row has no card without it. */
    preview?: TodayPreviewPayload
    /** Read by screen readers, which cannot reach the hover card. */
    description?: string | null
}

export function TodaySpacesRow({
    label,
    icon,
    to,
    active,
    dataAttr,
    action,
    badge,
    actionCount = 1,
    preview,
    description,
}: TodaySpacesRowProps): JSX.Element {
    const descriptionId = useId()
    const row = (
        <div className="group/row relative flex min-w-0 items-center">
            <Button
                size="row"
                left
                render={<LinkPrimitive to={to} />}
                aria-current={active ? 'page' : undefined}
                aria-describedby={description ? descriptionId : undefined}
                data-attr={dataAttr}
                className={cn(
                    'min-w-0 text-muted-foreground',
                    active && 'bg-fill-selected text-foreground',
                    action && !badge && (actionCount === 2 ? 'pr-12' : 'pr-8'),
                    badge && 'pr-24'
                )}
            >
                <span className="flex size-3.5 shrink-0 items-center justify-center">{icon}</span>
                <span className="min-w-0 flex-1 truncate">{label}</span>
            </Button>
            {description && (
                <span id={descriptionId} className="sr-only">
                    {description}
                </span>
            )}
            {(action || badge) && (
                <div className="absolute right-1 flex min-w-0 items-center gap-0.5">
                    {action && (
                        <div className="flex opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100">
                            {action}
                        </div>
                    )}
                    {badge}
                </div>
            )}
        </div>
    )
    if (!preview) {
        return row
    }
    return (
        <PreviewCard.Trigger
            handle={todayPreviewCardHandle}
            payload={preview}
            delay={PREVIEW_OPEN_DELAY_MS}
            closeDelay={PREVIEW_CLOSE_DELAY_MS}
            render={row}
        />
    )
}
