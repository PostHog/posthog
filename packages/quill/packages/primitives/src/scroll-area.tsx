import { ScrollArea as ScrollAreaPrimitive } from '@base-ui/react/scroll-area'
import * as React from 'react'

import { cn } from './lib/utils'

function ScrollArea({
    className,
    children,
    scrollShadows = true,
    ...props
}: ScrollAreaPrimitive.Root.Props & { scrollShadows?: boolean }): React.ReactElement {
    return (
        <ScrollAreaPrimitive.Root
            data-slot="scroll-area"
            // Just to keep around so we know it's a scroll area in case we merge props with another component
            data-component="scroll-area"
            data-scroll-shadows={scrollShadows}
            className={cn('relative', className)}
            {...props}
        >
            <ScrollAreaPrimitive.Viewport
                data-slot="scroll-area-viewport"
                className={cn(
                    'size-full rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1',
                    '[[data-scroll-shadows=true]_&]:before:content-[""] [[data-scroll-shadows=true]_&]:before:block [[data-scroll-shadows=true]_&]:before:left-0 [[data-scroll-shadows=true]_&]:before:w-full [[data-scroll-shadows=true]_&]:before:absolute [[data-scroll-shadows=true]_&]:before:pointer-events-none [[data-scroll-shadows=true]_&]:before:transition-[height] [[data-scroll-shadows=true]_&]:before:duration-100 [[data-scroll-shadows=true]_&]:before:ease-out [[data-scroll-shadows=true]_&]:before:top-0 [[data-scroll-shadows=true]_&]:before:z-1 [[data-scroll-shadows=true]_&]:before:[--scroll-area-overflow-y-start:inherit] [[data-scroll-shadows=true]_&]:before:h-[min(20px,var(--scroll-area-overflow-y-start))] ',
                    '[[data-scroll-shadows=true]_&]:after:content-[""] [[data-scroll-shadows=true]_&]:after:block [[data-scroll-shadows=true]_&]:after:left-0 [[data-scroll-shadows=true]_&]:after:w-full [[data-scroll-shadows=true]_&]:after:absolute [[data-scroll-shadows=true]_&]:after:pointer-events-none [[data-scroll-shadows=true]_&]:after:transition-[height] [[data-scroll-shadows=true]_&]:after:duration-100 [[data-scroll-shadows=true]_&]:after:ease-out [[data-scroll-shadows=true]_&]:after:bottom-0 [[data-scroll-shadows=true]_&]:after:z-1 [[data-scroll-shadows=true]_&]:after:[--scroll-area-overflow-y-end:inherit] [[data-scroll-shadows=true]_&]:after:h-[min(20px,var(--scroll-area-overflow-y-end,20px))]',
                    '[[data-scroll-shadows=true]_&]:before:bg-linear-to-b [[data-scroll-shadows=true]_&]:before:from-background [[data-scroll-shadows=true]_&]:before:to-transparent',
                    '[[data-scroll-shadows=true]_&]:after:bg-linear-to-t [[data-scroll-shadows=true]_&]:after:from-background [[data-scroll-shadows=true]_&]:after:to-transparent'
                )}
            >
                {children}
            </ScrollAreaPrimitive.Viewport>
            <ScrollBar />
            <ScrollAreaPrimitive.Corner />
        </ScrollAreaPrimitive.Root>
    )
}

function ScrollBar({
    className,
    orientation = 'vertical',
    ...props
}: ScrollAreaPrimitive.Scrollbar.Props): React.ReactElement {
    return (
        <ScrollAreaPrimitive.Scrollbar
            data-slot="scroll-area-scrollbar"
            data-orientation={orientation}
            orientation={orientation}
            className={cn(
                'flex touch-none p-px transition-colors select-none data-horizontal:h-2.5 data-horizontal:flex-col data-horizontal:border-t data-horizontal:border-t-transparent data-vertical:h-full data-vertical:w-2.5 data-vertical:border-s data-vertical:border-s-transparent',
                className
            )}
            {...props}
        >
            <ScrollAreaPrimitive.Thumb
                data-slot="scroll-area-thumb"
                className="relative flex-1 rounded-full bg-border"
            />
        </ScrollAreaPrimitive.Scrollbar>
    )
}

export { ScrollArea, ScrollBar }
