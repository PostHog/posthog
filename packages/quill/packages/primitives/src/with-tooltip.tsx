import * as React from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'

/**
 * Where the tooltip listens for the pointer.
 * - `self`: the element is the trigger. Use it only for elements that stay hoverable when disabled,
 *   such as `Button`, which keeps `focusableWhenDisabled` on, or a container whose disabled controls
 *   ignore the pointer, such as a number field or slider root.
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
        align,
        focusable = false,
    }: {
        target: TooltipTarget
        delay?: number
        side?: React.ComponentProps<typeof TooltipContent>['side']
        align?: React.ComponentProps<typeof TooltipContent>['align']
        /**
         * Puts the trigger in the tab order while there is content: the wrapper for `block` and
         * `inline`, the element itself for `self`. A disabled control leaves the tab order, so the
         * trigger is the only way a keyboard user can open its reason.
         */
        focusable?: boolean
    }
): React.ReactElement {
    const hasContent = hasTooltipContent(content)
    const tabIndex = focusable && hasContent ? 0 : undefined
    return (
        <Tooltip disabled={!hasContent}>
            {target === 'self' ? (
                <TooltipTrigger render={element} delay={delay} {...(tabIndex !== undefined && { tabIndex })} />
            ) : (
                <TooltipTrigger
                    delay={delay}
                    render={
                        target === 'block' ? (
                            <div tabIndex={tabIndex} />
                        ) : (
                            // Middle, not baseline: a checkbox's baseline comes from its check icon, so on a text line
                            // checking it would move the box and change the line's height.
                            <span className="inline-flex align-middle" tabIndex={tabIndex} />
                        )
                    }
                >
                    {element}
                </TooltipTrigger>
            )}
            {hasContent && (
                <TooltipContent side={side} align={align}>
                    {content}
                </TooltipContent>
            )}
        </Tooltip>
    )
}

/** Opens at the control's start edge, so a reason on a wide field or card sits beside where it starts. */
export function withDisabledReason(
    element: React.ReactElement,
    reason: React.ReactNode,
    options: Omit<Parameters<typeof withTooltip>[2], 'align'>
): React.ReactElement {
    return withTooltip(element, reason, { ...options, align: 'start' })
}
