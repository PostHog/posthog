import { Popover as PopoverPrimitive } from '@base-ui/react/popover'
import * as React from 'react'

import { cn } from './lib/utils'
import './popover.css'

function Popover({ ...props }: PopoverPrimitive.Root.Props): React.ReactElement {
    return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: PopoverPrimitive.Trigger.Props): React.ReactElement {
    return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverArrow({ className, ...props }: PopoverPrimitive.Arrow.Props): React.ReactElement {
    return (
        <PopoverPrimitive.Arrow data-slot="popover-arrow" className={cn('quill-popover__arrow', className)} {...props} />
    )
}

function PopoverContent({
    className,
    align = 'center',
    alignOffset = 0,
    side = 'bottom',
    arrow = false,
    // the arrow tip juts ~7px past the popup, so it needs a wider gap than a flush popover to clear the trigger
    sideOffset = arrow ? 9 : 4,
    arrowPadding,
    collisionAvoidance,
    container,
    children,
    ...props
}: PopoverPrimitive.Popup.Props &
    Pick<
        PopoverPrimitive.Positioner.Props,
        'align' | 'alignOffset' | 'side' | 'sideOffset' | 'arrowPadding' | 'collisionAvoidance'
    > &
    Pick<PopoverPrimitive.Portal.Props, 'container'> & {
        /** Renders a pointer connecting the popover to its trigger. */
        arrow?: boolean
    }): React.ReactElement {
    /*
     * `container` opt-in lets consumers mount the popover inside a
     * specific DOM subtree instead of `document.body`. Useful when
     * popover content needs to inherit ancestor context that doesn't
     * survive a portal jump — most notably CSS container queries
     * (`@container/<name>`), which only follow DOM ancestors. Pass a
     * ref to the container-query host and the portaled content can
     * read its size as if it were a direct child.
     */
    return (
        <PopoverPrimitive.Portal container={container}>
            <PopoverPrimitive.Positioner
                data-quill
                data-quill-portal="popover"
                align={align}
                alignOffset={alignOffset}
                side={side}
                sideOffset={sideOffset}
                arrowPadding={arrowPadding}
                collisionAvoidance={collisionAvoidance}
                className="isolate"
            >
                <PopoverPrimitive.Popup
                    data-slot="popover-content"
                    className={cn(
                        'quill-popover__content flex flex-col gap-4',
                        className
                    )}
                    {...props}
                >
                    {arrow && <PopoverArrow />}
                    {children}
                </PopoverPrimitive.Popup>
            </PopoverPrimitive.Positioner>
        </PopoverPrimitive.Portal>
    )
}

function PopoverHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="popover-header" className={cn('flex flex-col gap-1 text-xs', className)} {...props} />
}

function PopoverTitle({ className, ...props }: PopoverPrimitive.Title.Props): React.ReactElement {
    return (
        <PopoverPrimitive.Title
            data-slot="popover-title"
            className={cn('quill-popover__title', className)}
            {...props}
        />
    )
}

function PopoverDescription({ className, ...props }: PopoverPrimitive.Description.Props): React.ReactElement {
    return (
        <PopoverPrimitive.Description
            data-slot="popover-description"
            className={cn('quill-popover__description', className)}
            {...props}
        />
    )
}

export { Popover, PopoverArrow, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger }
