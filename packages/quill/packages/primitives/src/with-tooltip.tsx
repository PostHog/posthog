import * as React from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'

/**
 * Where the tooltip listens for the pointer.
 * - `self`: the element is the trigger. Use it only for elements that stay hoverable when disabled,
 *   such as `Button`, which keeps `focusableWhenDisabled` on.
 * - `block` / `inline`: a wrapper element is the trigger. Disabled menu items, checkboxes and switches
 *   ignore the pointer, so the wrapper has to catch it for them.
 */
export type TooltipTarget = 'self' | 'block' | 'inline'

/** True when a `tooltip` or `disabledReason` prop has something to show. */
export function hasTooltipContent(content: React.ReactNode): boolean {
    return content !== undefined && content !== null && content !== false && content !== ''
}

/**
 * Internal helper behind the `tooltip` and `disabledReason` props of quill primitives.
 * Returns `element` unchanged when there is no content, so callers can pass it unconditionally.
 */
export function withTooltip(
    element: React.ReactElement,
    content: React.ReactNode,
    {
        target,
        delay,
        side,
    }: { target: TooltipTarget; delay?: number; side?: React.ComponentProps<typeof TooltipContent>['side'] }
): React.ReactElement {
    if (!hasTooltipContent(content)) {
        return element
    }
    return (
        <Tooltip>
            {target === 'self' ? (
                <TooltipTrigger render={element} delay={delay} />
            ) : (
                <TooltipTrigger
                    delay={delay}
                    render={target === 'block' ? <div /> : <span className="inline-flex" />}
                >
                    {element}
                </TooltipTrigger>
            )}
            <TooltipContent side={side}>{content}</TooltipContent>
        </Tooltip>
    )
}
