import { type FocusEvent, type ReactNode, useCallback, useEffect, useRef, useState } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { pointerMovedRecently, trackPointer } from '~/layout/today/todayPointer'

const OPEN_DELAY_MS = 300
const CLOSE_DELAY_MS = 150

export function TodayPulseHoverCard({
    children,
    card,
    onOpenChange,
}: {
    children: ReactNode
    card: ReactNode
    onOpenChange: (open: boolean) => void
}): JSX.Element {
    const [open, setOpenState] = useState(false)
    const openRef = useRef(false)
    const onOpenChangeRef = useRef(onOpenChange)
    onOpenChangeRef.current = onOpenChange
    const setOpen = (next: boolean): void => {
        if (next !== openRef.current) {
            onOpenChange(next)
        }
        openRef.current = next
        setOpenState(next)
    }
    useEffect(
        () => () => {
            if (openRef.current) {
                onOpenChangeRef.current(false)
            }
        },
        []
    )
    const popupRef = useRef<HTMLDivElement>(null)
    const triggerRef = useCallback((): void => trackPointer(), [])
    return (
        <Popover
            open={open}
            onOpenChange={(next, details) => {
                if (next && details.reason === 'trigger-hover' && !pointerMovedRecently()) {
                    return
                }
                setOpen(next)
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
                onFocus={() => !open && setOpen(true)}
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
