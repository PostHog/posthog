import { Popover as PopoverPrimitive } from '@base-ui/react/popover'
import * as React from 'react'

import { cn } from './lib/utils'
import './popover.css'

function Popover({ ...props }: PopoverPrimitive.Root.Props): React.ReactElement {
    return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

const PopoverTrigger = React.forwardRef<HTMLButtonElement, PopoverPrimitive.Trigger.Props>(
    function PopoverTrigger(props, ref) {
        return <PopoverPrimitive.Trigger ref={ref} data-slot="popover-trigger" {...props} />
    }
)

const PopoverArrow = React.forwardRef<React.ComponentRef<typeof PopoverPrimitive.Arrow>, PopoverPrimitive.Arrow.Props>(
    function PopoverArrow({ className, ...props }, ref) {
        return (
            <PopoverPrimitive.Arrow
                ref={ref}
                data-slot="popover-arrow"
                className={cn('quill-popover__arrow', className)}
                {...props}
            />
        )
    }
)

const PopoverContent = React.forwardRef<
    React.ComponentRef<typeof PopoverPrimitive.Popup>,
    PopoverPrimitive.Popup.Props &
        Pick<
            PopoverPrimitive.Positioner.Props,
            'align' | 'alignOffset' | 'side' | 'sideOffset' | 'arrowPadding' | 'collisionAvoidance'
        > &
        Pick<PopoverPrimitive.Portal.Props, 'container'> & {
            /** Renders a pointer connecting the popover to its trigger. */
            arrow?: boolean
        }
>(function PopoverContent(
    {
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
    },
    ref
) {
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
                    ref={ref}
                    data-slot="popover-content"
                    className={cn('quill-popover__content flex flex-col gap-4', className)}
                    {...props}
                >
                    {arrow && <PopoverArrow />}
                    {children}
                </PopoverPrimitive.Popup>
            </PopoverPrimitive.Positioner>
        </PopoverPrimitive.Portal>
    )
})

const PopoverHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function PopoverHeader(
    { className, ...props },
    ref
) {
    return (
        <div ref={ref} data-slot="popover-header" className={cn('flex flex-col gap-1 text-xs', className)} {...props} />
    )
})

const PopoverTitle = React.forwardRef<React.ComponentRef<typeof PopoverPrimitive.Title>, PopoverPrimitive.Title.Props>(
    function PopoverTitle({ className, ...props }, ref) {
        return (
            <PopoverPrimitive.Title
                ref={ref}
                data-slot="popover-title"
                className={cn('quill-popover__title', className)}
                {...props}
            />
        )
    }
)

const PopoverDescription = React.forwardRef<
    React.ComponentRef<typeof PopoverPrimitive.Description>,
    PopoverPrimitive.Description.Props
>(function PopoverDescription({ className, ...props }, ref) {
    return (
        <PopoverPrimitive.Description
            ref={ref}
            data-slot="popover-description"
            className={cn('quill-popover__description', className)}
            {...props}
        />
    )
})

export { Popover, PopoverArrow, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger }
