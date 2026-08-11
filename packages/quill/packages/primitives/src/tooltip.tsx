import { Tooltip as TooltipPrimitive } from '@base-ui/react/tooltip'
import * as React from 'react'

import { cn } from './lib/utils'
import './tooltip.css'

/**
 * Provides a shared delay for multiple tooltips. The grouping logic ensures that
 * once a tooltip becomes visible, the adjacent tooltips will be shown instantly.
 *
 * Documentation: [Base UI Tooltip](https://base-ui.com/react/components/tooltip)
 *
 * @baseui Tooltip.Provider
 */
function TooltipProvider({ delay = 250, ...props }: TooltipPrimitive.Provider.Props): React.ReactElement {
    return <TooltipPrimitive.Provider data-slot="tooltip-provider" delay={delay} {...props} />
}

/**
 * Groups all parts of the tooltip.
 * Doesn't render its own HTML element.
 *
 * Documentation: [Base UI Tooltip](https://base-ui.com/react/components/tooltip)
 *
 * @baseui Tooltip.Root
 */
function Tooltip({ ...props }: TooltipPrimitive.Root.Props): React.ReactElement {
    return <TooltipPrimitive.Root data-slot="tooltip" {...props} />
}

/**
 * An element to attach the tooltip to.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Tooltip](https://base-ui.com/react/components/tooltip)
 *
 * @baseui Tooltip.Trigger
 */
function TooltipTrigger({ ...props }: TooltipPrimitive.Trigger.Props): React.ReactElement {
    return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

/**
 * A container for the tooltip contents.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Tooltip](https://base-ui.com/react/components/tooltip)
 *
 * @baseui Tooltip.Popup
 */
function TooltipContent({
    className,
    side = 'top',
    sideOffset = 4,
    align = 'center',
    alignOffset = 0,
    children,
    ...props
}: TooltipPrimitive.Popup.Props &
    Pick<TooltipPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>): React.ReactElement {
    return (
        <TooltipPrimitive.Portal>
            <TooltipPrimitive.Positioner
                data-quill
                data-quill-portal="tooltip"
                align={align}
                alignOffset={alignOffset}
                side={side}
                sideOffset={sideOffset}
                className="isolate"
            >
                <TooltipPrimitive.Popup
                    data-slot="tooltip-content"
                    className={cn('quill-tooltip__content inline-flex items-center gap-1.5', className)}
                    {...props}
                >
                    {children}
                    <TooltipPrimitive.Arrow className="quill-tooltip__arrow data-[side=bottom]:top-[5px] data-[side=inline-end]:top-1/2! data-[side=inline-end]:-start-1 data-[side=inline-end]:-translate-y-1/2 data-[side=inline-start]:top-1/2! data-[side=inline-start]:-end-1 data-[side=inline-start]:-translate-y-1/2 data-[side=left]:top-1/2! data-[side=left]:-right-[2px] data-[side=left]:-translate-y-1/2 data-[side=right]:top-1/2! data-[side=right]:-left-[2px] data-[side=right]:-translate-y-1/2 data-[side=top]:-bottom-[9px]" />
                </TooltipPrimitive.Popup>
            </TooltipPrimitive.Positioner>
        </TooltipPrimitive.Portal>
    )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
