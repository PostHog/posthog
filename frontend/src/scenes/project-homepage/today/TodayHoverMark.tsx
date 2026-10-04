import { PreviewCard } from '@base-ui/react/preview-card'
import { type ReactNode, useState } from 'react'

import { Card, cn } from '@posthog/quill'

const OPEN_DELAY_MS = 250
const CLOSE_DELAY_MS = 120
const CARD_GAP_PX = 10

const RECENT_MOVE_MS = 1000
let lastPointerMove = Number.NEGATIVE_INFINITY

if (typeof window !== 'undefined') {
    window.addEventListener('pointermove', () => (lastPointerMove = performance.now()), { passive: true })
}

function pointerMovedRecently(): boolean {
    return performance.now() - lastPointerMove < RECENT_MOVE_MS
}

function cardAnchor(trigger: HTMLElement | null): Element | undefined {
    return trigger?.closest('li, p') ?? undefined
}

export function TodayHoverMark({
    className,
    dataAttr,
    children,
    card,
}: {
    className: string
    dataAttr: string
    children: ReactNode
    card: ReactNode
}): JSX.Element {
    const [trigger, setTrigger] = useState<HTMLElement | null>(null)
    const [open, setOpen] = useState(false)
    return (
        <PreviewCard.Root
            open={open}
            onOpenChange={(next, details) => {
                const hoverWithoutMove = details.reason === 'trigger-hover' && !pointerMovedRecently()
                if (!next || !hoverWithoutMove) {
                    setOpen(next)
                }
            }}
        >
            <PreviewCard.Trigger
                delay={OPEN_DELAY_MS}
                closeDelay={CLOSE_DELAY_MS}
                ref={setTrigger}
                render={<span tabIndex={0} />}
                onClick={() => setOpen(true)}
                className={cn('TodayHoverMark', className)}
                data-attr={dataAttr}
            >
                {children}
            </PreviewCard.Trigger>
            <PreviewCard.Portal>
                <PreviewCard.Positioner
                    data-quill
                    data-quill-portal="popover"
                    className="[--quill-z-popover:var(--z-popover-with-chart)]"
                    anchor={cardAnchor(trigger)}
                    side="bottom"
                    align="start"
                    sideOffset={CARD_GAP_PX}
                >
                    <PreviewCard.Popup className="TodayHoverMark__popup outline-none">
                        <Card
                            size="sm"
                            className="TodayHoverMark__card w-[var(--anchor-width)] gap-0 border border-border py-0"
                        >
                            {card}
                        </Card>
                    </PreviewCard.Popup>
                </PreviewCard.Positioner>
            </PreviewCard.Portal>
        </PreviewCard.Root>
    )
}
