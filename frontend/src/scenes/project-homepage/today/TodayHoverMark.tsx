import { Popover } from '@base-ui/react/popover'
import { type ReactNode, useCallback, useState } from 'react'

import { Card, cn } from '@posthog/quill'

const OPEN_DELAY_MS = 250
const CLOSE_DELAY_MS = 120
const CARD_GAP_PX = 10

const RECENT_MOVE_MS = 1000
let lastPointerMove = Number.NEGATIVE_INFINITY
let tracksPointer = false

function trackPointerMoves(): void {
    if (tracksPointer) {
        return
    }
    tracksPointer = true
    window.addEventListener('pointermove', () => (lastPointerMove = performance.now()), { passive: true })
}

function pointerMovedRecently(): boolean {
    return performance.now() - lastPointerMove < RECENT_MOVE_MS
}

function cardAnchor(trigger: HTMLElement | null): Element | undefined {
    return trigger?.closest('[data-today-figures]') ?? trigger?.closest('li, p') ?? undefined
}

export function TodayHoverMark({
    className,
    dataAttr,
    children,
    card,
    onOpen,
}: {
    className: string
    dataAttr: string
    children: ReactNode
    card: ReactNode
    onOpen: () => void
}): JSX.Element {
    const [trigger, setTrigger] = useState<HTMLElement | null>(null)
    const [open, setOpen] = useState(false)
    const triggerRef = useCallback((node: HTMLElement | null): void => {
        trackPointerMoves()
        setTrigger(node)
    }, [])
    return (
        <Popover.Root
            open={open}
            onOpenChange={(next, details) => {
                const hoverWithoutMove = details.reason === 'trigger-hover' && !pointerMovedRecently()
                if (next && hoverWithoutMove) {
                    return
                }
                setOpen(next)
                if (next) {
                    onOpen()
                }
            }}
        >
            <Popover.Trigger
                openOnHover
                delay={OPEN_DELAY_MS}
                closeDelay={CLOSE_DELAY_MS}
                nativeButton={false}
                ref={triggerRef}
                render={<span />}
                className={cn('TodayHoverMark', className)}
                data-attr={dataAttr}
            >
                {children}
            </Popover.Trigger>
            <Popover.Portal>
                <Popover.Positioner
                    data-quill
                    data-quill-portal="popover"
                    className="[--quill-z-popover:var(--z-popover-with-chart)]"
                    anchor={cardAnchor(trigger)}
                    side="bottom"
                    align="start"
                    sideOffset={CARD_GAP_PX}
                >
                    <Popover.Popup className="TodayHoverMark__popup outline-none">
                        <Card
                            size="sm"
                            className="TodayHoverMark__card w-[var(--anchor-width)] gap-0 border border-border py-0"
                        >
                            {card}
                        </Card>
                    </Popover.Popup>
                </Popover.Positioner>
            </Popover.Portal>
        </Popover.Root>
    )
}
