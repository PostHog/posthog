import { Popover as PopoverPrimitive } from '@base-ui/react/popover'
import * as React from 'react'

import { cn } from './lib/utils'
import './popover.css'

/**
 * Groups all parts of the popover.
 * Doesn't render its own HTML element.
 *
 * Documentation: [Base UI Popover](https://base-ui.com/react/components/popover)
 *
 * @baseui Popover.Root
 */
function Popover({ ...props }: PopoverPrimitive.Root.Props): React.ReactElement {
    return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

/**
 * A button that opens the popover.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Popover](https://base-ui.com/react/components/popover)
 *
 * @baseui Popover.Trigger
 */
function PopoverTrigger({ ...props }: PopoverPrimitive.Trigger.Props): React.ReactElement {
    return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

/**
 * A container for the popover contents.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Popover](https://base-ui.com/react/components/popover)
 *
 * @baseui Popover.Popup
 */
function PopoverContent({
    className,
    align = 'center',
    alignOffset = 0,
    side = 'bottom',
    sideOffset = 4,
    collisionAvoidance,
    container,
    ...props
}: PopoverPrimitive.Popup.Props &
    Pick<PopoverPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset' | 'collisionAvoidance'> &
    Pick<PopoverPrimitive.Portal.Props, 'container'>): React.ReactElement {
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
                />
            </PopoverPrimitive.Positioner>
        </PopoverPrimitive.Portal>
    )
}

function PopoverHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="popover-header" className={cn('flex flex-col gap-1 text-xs', className)} {...props} />
}

/**
 * A heading that labels the popover.
 * Renders an `<h2>` element.
 *
 * Documentation: [Base UI Popover](https://base-ui.com/react/components/popover)
 *
 * @baseui Popover.Title
 */
function PopoverTitle({ className, ...props }: PopoverPrimitive.Title.Props): React.ReactElement {
    return (
        <PopoverPrimitive.Title
            data-slot="popover-title"
            className={cn('quill-popover__title', className)}
            {...props}
        />
    )
}

/**
 * A paragraph with additional information about the popover.
 * Renders a `<p>` element.
 *
 * Documentation: [Base UI Popover](https://base-ui.com/react/components/popover)
 *
 * @baseui Popover.Description
 */
function PopoverDescription({ className, ...props }: PopoverPrimitive.Description.Props): React.ReactElement {
    return (
        <PopoverPrimitive.Description
            data-slot="popover-description"
            className={cn('quill-popover__description', className)}
            {...props}
        />
    )
}

export { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger }
