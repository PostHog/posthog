import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, RefObject } from 'react'

import { Button, Popover, PopoverContent, Text } from '@posthog/quill'

import { todaySeenLogic } from './todaySeenLogic'
import { todayTourLogic } from './todayTourLogic'

/**
 * A notice pointing at a control, shown to each person once. Dismissing it in any way (the button, an outside click,
 * Esc) records it on the user, so it never comes back on another device either.
 */
export function TodayOneTimeNotice({
    noticeKey,
    anchor,
    title,
    description,
    side,
    align,
    hidden = false,
}: {
    /** pinned: key in the user's server-side `has_seen_product_intro_for`. Renaming it shows the notice again. */
    noticeKey: string
    anchor: RefObject<HTMLElement>
    title: ReactNode
    description: ReactNode
    side: 'top' | 'right' | 'bottom' | 'left'
    align: 'start' | 'center' | 'end'
    /** Holds the notice back without dismissing it, while something else has the person's attention. */
    hidden?: boolean
}): JSX.Element | null {
    const { isSeen } = useValues(todaySeenLogic)
    const { markSeen } = useActions(todaySeenLogic)
    const { tourActive } = useValues(todayTourLogic)

    if (isSeen(noticeKey)) {
        return null
    }

    const dismiss = (): void => {
        markSeen(noticeKey)
        // pinned: analytics event name and property. Renaming them breaks dashboards.
        posthog.capture('today notice dismissed', { notice: noticeKey })
    }

    return (
        <Popover
            // The tour's own card points at the same controls, so the notice waits for it to end.
            open={!tourActive && !hidden}
            onOpenChange={(open) => {
                if (!open) {
                    dismiss()
                }
            }}
        >
            <PopoverContent anchor={anchor} side={side} align={align} arrow className="max-w-64">
                <div className="flex flex-col gap-1">
                    <Text size="sm" weight="semibold" render={<h3 />} className="m-0">
                        {title}
                    </Text>
                    <Text size="xs" variant="muted" className="m-0">
                        {description}
                    </Text>
                </div>
                <Button variant="outline" size="sm" className="self-end" onClick={dismiss}>
                    Got it
                </Button>
            </PopoverContent>
        </Popover>
    )
}
