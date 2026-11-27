import { type ReactNode, useState } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

/** A tooltip that a click opens too, because a touch screen has no hover. Long text stops after six lines. */
export function TapTooltip({
    text,
    className,
    children,
}: {
    text: string
    className?: string
    children: ReactNode
}): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <Tooltip open={open} onOpenChange={setOpen}>
            <TooltipTrigger
                // A click opens the tooltip and must not close it again.
                closeOnClick={false}
                render={<button type="button" className={className} aria-label={text} onClick={() => setOpen(true)} />}
            >
                {children}
            </TooltipTrigger>
            <TooltipContent className="max-w-80">
                <span className="line-clamp-6">{text}</span>
            </TooltipContent>
        </Tooltip>
    )
}
