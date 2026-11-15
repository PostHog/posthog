import './tooltip.css'

import { Tooltip as TooltipPrimitive } from '@base-ui/react/tooltip'
import * as React from 'react'

import { cn } from './lib/utils'

function TooltipProvider({ delay = 250, ...props }: TooltipPrimitive.Provider.Props): React.ReactElement {
    return <TooltipPrimitive.Provider data-slot="tooltip-provider" delay={delay} {...props} />
}

const TooltipGlideContext = React.createContext(false)
const TooltipTracksCursorContext = React.createContext(false)

const createTooltipHandle = TooltipPrimitive.createHandle

function Tooltip<Payload>({
    onOpenChangeComplete,
    disableHoverablePopup,
    ...props
}: TooltipPrimitive.Root.Props<Payload>): React.ReactElement {
    // A tooltip shared through a handle glides between its triggers. It starts once the tooltip has
    // opened in place, so the first placement does not slide in from the corner of the page.
    const [glide, setGlide] = React.useState(false)
    // A tooltip that follows the pointer sits under it, so it must never take a hover or a click.
    // Otherwise a press or a release lands on the tooltip instead of the page below it.
    const tracksCursor = props.trackCursorAxis !== undefined && props.trackCursorAxis !== 'none'
    return (
        <TooltipGlideContext.Provider value={glide}>
            <TooltipTracksCursorContext.Provider value={tracksCursor}>
                <TooltipPrimitive.Root
                    data-slot="tooltip"
                    onOpenChangeComplete={(open) => {
                        setGlide(open && props.handle !== undefined)
                        onOpenChangeComplete?.(open)
                    }}
                    disableHoverablePopup={disableHoverablePopup ?? tracksCursor}
                    {...props}
                />
            </TooltipTracksCursorContext.Provider>
        </TooltipGlideContext.Provider>
    )
}

// The cast restores the `Payload` generic, because forwardRef cannot carry a generic signature.
// Props already type `ref`, so adding React.RefAttributes would break contextual typing of `render` callbacks.
const TooltipTrigger = React.forwardRef(function TooltipTrigger(
    props: TooltipPrimitive.Trigger.Props,
    ref: React.ForwardedRef<HTMLButtonElement>
): React.ReactElement {
    return <TooltipPrimitive.Trigger ref={ref} data-slot="tooltip-trigger" {...props} />
}) as <Payload>(props: TooltipPrimitive.Trigger.Props<Payload>) => React.ReactElement

const TooltipContent = React.forwardRef<
    React.ComponentRef<typeof TooltipPrimitive.Popup>,
    TooltipPrimitive.Popup.Props &
        Pick<TooltipPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>
>(function TooltipContent(
    { className, side = 'top', sideOffset = 4, align = 'center', alignOffset = 0, children, ...props },
    ref
) {
    const glide = React.useContext(TooltipGlideContext)
    const tracksCursor = React.useContext(TooltipTracksCursorContext)
    return (
        <TooltipPrimitive.Portal>
            <TooltipPrimitive.Positioner
                data-quill
                data-quill-portal="tooltip"
                align={align}
                alignOffset={alignOffset}
                side={side}
                sideOffset={sideOffset}
                data-glide={glide ? '' : undefined}
                className={cn('quill-tooltip__positioner isolate', tracksCursor && 'pointer-events-none')}
            >
                <TooltipPrimitive.Popup
                    ref={ref}
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
})

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider, createTooltipHandle }
