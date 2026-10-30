import { ReactNode, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconLive } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

export function OngoingRecordingsGroup({
    count,
    holdsActive,
    defaultOpen = false,
    children,
}: {
    count: number
    holdsActive: boolean
    defaultOpen?: boolean
    children: ReactNode
}): JSX.Element | null {
    // null follows the selection. A click pins a choice until the selection next moves into the group
    const [choice, setChoice] = useState<boolean | null>(null)
    const [wasHoldingActive, setWasHoldingActive] = useState(holdsActive)
    if (holdsActive !== wasHoldingActive) {
        setWasHoldingActive(holdsActive)
        if (holdsActive) {
            setChoice(null)
        }
    }
    if (count === 0) {
        return null
    }
    const expanded = choice ?? (holdsActive || defaultOpen)

    return (
        <div className="border-b">
            <LemonButton
                fullWidth
                size="xsmall"
                className="rounded-none bg-surface-secondary"
                icon={<IconLive className="text-primary-3000" />}
                sideIcon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setChoice(!expanded)}
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
