import { ReactNode, useState } from 'react'

import { IconLive } from '@posthog/icons'
import { Badge, Collapsible, CollapsibleContent, CollapsibleTrigger } from '@posthog/quill'

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
        <Collapsible
            data-quill
            open={expanded}
            onOpenChange={(open) => setChoice(open)}
            className="border-b border-border"
        >
            <CollapsibleTrigger className="w-full rounded-none bg-muted" data-attr="list-ongoing-toggle">
                <IconLive className="text-primary-3000" />
                <span className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground font-semibold">
                    Still recording
                    <Badge>{count}</Badge>
                </span>
                <span className="grow" />
            </CollapsibleTrigger>
            <CollapsibleContent>{children}</CollapsibleContent>
        </Collapsible>
    )
}
