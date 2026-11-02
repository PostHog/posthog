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
 * Callers pass it unconditionally. Without content the tooltip is disabled rather than left out,
 * so the control keeps the same ancestors when a reason appears or clears and React does not
 * remount it, which would reset an uncontrolled Checkbox or Switch.
 */
export function withTooltip(
    element: React.ReactElement,
    content: React.ReactNode,
    {
        target,
        delay,
        side,
        focusable = false,
    }: {
        target: TooltipTarget
        delay?: number
        side?: React.ComponentProps<typeof TooltipContent>['side']
        /**
         * Puts a `block` or `inline` wrapper in the tab order. A disabled control leaves the tab
         * order, so the wrapper is the only way a keyboard user can open its reason.
         */
        focusable?: boolean
    }
): React.ReactElement {
    const hasContent = hasTooltipContent(content)
    const tabIndex = focusable && hasContent ? 0 : undefined
    return (
        <Tooltip disabled={!hasContent}>
            {target === 'self' ? (
                <TooltipTrigger render={element} delay={delay} />
            ) : (
                <TooltipTrigger
                    delay={delay}
                    render={
                        target === 'block' ? (
                            <div tabIndex={tabIndex} />
                        ) : (
                            <span className="inline-flex" tabIndex={tabIndex} />
                        )
                    }
                >
                    {element}
                </TooltipTrigger>
            )}
            {hasContent && <TooltipContent side={side}>{content}</TooltipContent>}
        </Tooltip>
    )
}
