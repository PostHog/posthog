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

function PopoverContent({
    className,
    align = 'center',
    alignOffset = 0,
    side = 'bottom',
    sideOffset = 4,
    ...props
}: PopoverPrimitive.Popup.Props &
    Pick<PopoverPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>): React.ReactElement {
    return (
        <PopoverPrimitive.Portal>
            <PopoverPrimitive.Positioner
                data-quill
                align={align}
                alignOffset={alignOffset}
                side={side}
                sideOffset={sideOffset}
                className="isolate z-50"
            >
                <PopoverPrimitive.Popup
                    data-slot="popover-content"
                    className={cn(
                        'quill-popover__content flex flex-col gap-4 duration-100 data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-start-2 data-[side=inline-start]:slide-in-from-end-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95',
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

export { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger }
