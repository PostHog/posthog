import { InfoIcon } from 'lucide-react'
import * as React from 'react'

import { Button, cn, Popover, PopoverContent, PopoverDescription, PopoverTrigger } from '@posthog/quill-primitives'

type PopoverRootProps = React.ComponentProps<typeof Popover>
type PopoverContentProps = React.ComponentProps<typeof PopoverContent>

export interface InfotipProps {
    /**
     * Names the trigger and the popup for screen readers, for example "About average position". Say which
     * value it explains, because a page often has several infotips and each needs a distinct name.
     */
    label: string
    /** The explanation. Keep it to short text, optionally with an inline link: it renders inside a `<p>`. */
    children: React.ReactNode
    side?: PopoverContentProps['side']
    align?: PopoverContentProps['align']
    /** Milliseconds the pointer rests on the icon before the popup opens. */
    delay?: number
    className?: string
    contentClassName?: string
}

/**
 * An info icon that explains the value next to it. Hover opens it, and a click keeps it open until
 * Escape or a click outside. Unlike a tooltip, the trigger is a real button, so keyboard, touch and
 * screen reader users reach the same text.
 */
const Infotip = React.forwardRef<HTMLButtonElement, InfotipProps>(function Infotip(
    { label, children, side = 'top', align = 'center', delay = 100, className, contentClassName },
    ref
) {
    const pinned = React.useRef(false)
    // Base UI closes a popover opened by hover when the trigger is clicked more than 500ms later. People
    // click an info icon to keep the text up, so that click pins the popup, and the next one closes it.
    const handleOpenChange: PopoverRootProps['onOpenChange'] = (open, details) => {
        if (open) {
            pinned.current = details.reason === 'trigger-press'
            return
        }
        if (details.reason === 'trigger-press' && !pinned.current) {
            pinned.current = true
            details.cancel()
            return
        }
        if (details.reason === 'trigger-hover' && pinned.current) {
            details.cancel()
            return
        }
        pinned.current = false
    }
    return (
        <Popover onOpenChange={handleOpenChange}>
            <PopoverTrigger
                ref={ref}
                openOnHover
                delay={delay}
                closeDelay={100}
                render={
                    <Button
                        variant="default"
                        size="icon-xs"
                        aria-label={label}
                        className={cn('text-muted-foreground', className)}
                    />
                }
            >
                <InfoIcon aria-hidden />
            </PopoverTrigger>
            <PopoverContent
                side={side}
                align={align}
                arrow
                aria-label={label}
                data-slot="infotip-content"
                className={cn('w-auto max-w-xs gap-0', contentClassName)}
            >
                <PopoverDescription className="text-foreground">{children}</PopoverDescription>
            </PopoverContent>
        </Popover>
    )
})

export { Infotip }
