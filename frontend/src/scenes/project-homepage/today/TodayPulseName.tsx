import { type ReactNode, useRef, useState } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function TodayPulseName({ name, icon }: { name: string; icon?: ReactNode }): JSX.Element {
    const ref = useRef<HTMLSpanElement>(null)
    const [open, setOpen] = useState(false)
    return (
        <Tooltip open={open} onOpenChange={(next) => setOpen(next && isClamped(ref.current))}>
            <TooltipTrigger render={<span ref={ref} className="TodayPulse__name" />}>
                {icon}
                <span>{name}</span>
            </TooltipTrigger>
            <TooltipContent side="top">{name}</TooltipContent>
        </Tooltip>
    )
}

function isClamped(element: HTMLElement | null): boolean {
    return !!element && element.scrollHeight > element.clientHeight
}
