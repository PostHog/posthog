import { ReactNode, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconLive } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

/** Recordings still receiving data, folded above the results so the list opens on finished ones. */
export function OngoingRecordingsGroup({
    count,
    holdsActive,
    children,
}: {
    count: number
    /** The recording being watched is in the group, so it stays open rather than hiding the selection. */
    holdsActive: boolean
    children: ReactNode
}): JSX.Element | null {
    const [open, setOpen] = useState(false)
    if (count === 0) {
        return null
    }
    const expanded = open || holdsActive

    return (
        <div className="border-b">
            <LemonButton
                fullWidth
                size="xsmall"
                className="rounded-none bg-surface-secondary"
                icon={<IconLive className="text-primary-3000" />}
                sideIcon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setOpen(!expanded)}
                data-attr="list-ongoing-toggle"
            >
                <span className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-secondary font-semibold">
                    Still recording
                    <LemonBadge.Number count={count} status="muted" size="small" />
                </span>
            </LemonButton>
            {expanded && children}
        </div>
    )
}
