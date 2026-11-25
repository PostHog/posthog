import { InfoIcon } from 'lucide-react'
import * as React from 'react'

import { Button, cn, Popover, PopoverContent, PopoverDescription, PopoverTrigger } from '@posthog/quill-primitives'

type PopoverContentProps = React.ComponentProps<typeof PopoverContent>

export interface InfotipProps {
    /** The screen reader name of the icon and the popup. Name the value, such as "About average position". */
    label: string
    /** The explanation. Keep it short: text, an inline link, or a short list. */
    children: React.ReactNode
    side?: PopoverContentProps['side']
    align?: PopoverContentProps['align']
    /** The `data-attr` of the icon button, so product analytics can tell this infotip's opens apart. */
    dataAttr?: string
    className?: string
    contentClassName?: string
}

const Infotip = React.forwardRef<HTMLButtonElement, InfotipProps>(function Infotip(
    { label, children, side = 'top', align = 'center', dataAttr, className, contentClassName },
    ref
) {
    return (
        <Popover>
            <PopoverTrigger
                ref={ref}
                // Info icons sit in sortable headers, collapse headers and clickable cards, so a click or key
                // press that opens the popup must not also reach the parent's handler. Inside a link, the
                // browser would then follow the href itself, so the default action is cancelled too. Escape is
                // left alone, because Base UI listens for it on the document.
                onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                }}
                onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.stopPropagation()
                    }
                }}
                render={
                    <Button
                        variant="default"
                        size="icon-xs"
                        aria-label={label}
                        data-attr={dataAttr}
                        // The button draws 16px, so it fits a line of small text without growing it or being
                        // clipped by a truncated parent, and its focus ring sits inside it. The ::after layer
                        // grows the touch target to 24px, the WCAG 2.5.8 minimum.
                        className={cn(
                            "relative size-4 align-middle text-muted-foreground focus-visible:ring-inset after:absolute after:-inset-1 after:content-['']",
                            className
                        )}
                    />
                }
            >
                <InfoIcon aria-hidden className="size-3.5" />
            </PopoverTrigger>
            <PopoverContent
                side={side}
                align={align}
                arrow
                aria-label={label}
                data-slot="infotip-content"
                // React bubbles events out of a portal through the component tree, so a click on the popup
                // would otherwise reach the same parent handler.
                onClick={(event) => event.stopPropagation()}
                className={cn('w-auto max-w-xs gap-0', contentClassName)}
            >
                <PopoverDescription render={<div />} className="text-foreground">
                    {children}
                </PopoverDescription>
            </PopoverContent>
        </Popover>
    )
})

export { Infotip }
