import { type FocusEvent, type ReactNode, useCallback, useRef, useState } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { pointerMovedRecently, trackPointer } from '~/layout/today/todayPointer'

const OPEN_DELAY_MS = 300
const CLOSE_DELAY_MS = 150

export function TodayPulseHoverCard({
    children,
    card,
    onOpen,
}: {
    children: ReactNode
    card: ReactNode
    onOpen: () => void
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const popupRef = useRef<HTMLDivElement>(null)
    const triggerRef = useCallback((): void => trackPointer(), [])
    const show = (next: boolean): void => {
        setOpen(next)
        if (next) {
            onOpen()
        }
    }
    return (
        <Popover
            open={open}
            onOpenChange={(next, details) => {
                if (next && details.reason === 'trigger-hover' && !pointerMovedRecently()) {
                    return
                }
                show(next)
            }}
        >
            <PopoverTrigger
                openOnHover
                delay={OPEN_DELAY_MS}
                closeDelay={CLOSE_DELAY_MS}
                nativeButton={false}
                ref={triggerRef}
                render={<div />}
                className="TodayPulse__trigger"
                onFocus={() => !open && show(true)}
                onBlur={(event: FocusEvent) => {
                    if (!popupRef.current?.contains(event.relatedTarget as Node | null)) {
                        setOpen(false)
                    }
                }}
            >
                {children}
            </PopoverTrigger>
            <PopoverContent
                ref={popupRef}
                side="bottom"
                align="start"
                sideOffset={8}
                initialFocus={false}
                className="w-85 gap-0 p-0"
            >
                {card}
            </PopoverContent>
        </Popover>
    )
}
