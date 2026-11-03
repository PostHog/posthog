import * as React from 'react'
import * as ResizablePrimitive from 'react-resizable-panels'

import { cn } from './lib/utils'
import './resizable.css'

function ResizablePanelGroup({ className, ...props }: ResizablePrimitive.GroupProps): React.ReactElement {
    return (
        <ResizablePrimitive.Group
            data-quill
            data-slot="resizable-panel-group"
            className={cn(
                'group/resizable-panel-group flex h-full w-full aria-[orientation=vertical]:flex-col',
                className
            )}
            {...props}
        />
    )
}

function ResizablePanel({ ...props }: ResizablePrimitive.PanelProps): React.ReactElement {
    return <ResizablePrimitive.Panel data-slot="resizable-panel" {...props} />
}

function ResizableHandle({
    withHandle,
    className,
    ...props
}: ResizablePrimitive.SeparatorProps & {
    withHandle?: boolean
}): React.ReactElement {
    const elementRef = React.useRef<HTMLDivElement>(null)

    React.useEffect(() => {
        const el = elementRef.current
        if (!el) {
            return
        }
        const handlePointerUp = (): void => {
            el.blur()
        }
        el.addEventListener('pointerup', handlePointerUp)
        return () => el.removeEventListener('pointerup', handlePointerUp)
    }, [])

    return (
        <ResizablePrimitive.Separator
            data-slot="resizable-handle"
            elementRef={elementRef}
            className={cn('quill-resizable__handle flex items-center justify-center', className)}
            {...props}
        >
            {withHandle && <div />}
        </ResizablePrimitive.Separator>
    )
}

/**
 * The look of `ResizableHandle` (a line with a pill) without a panel group, for an edge that resizes something
 * else, such as a popup. The caller handles the drag. A `render` target, so it can sit inside a `TooltipTrigger`.
 */
const ResizeGrip = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & { orientation?: 'vertical' | 'horizontal'; withHandle?: boolean }
>(function ResizeGrip({ orientation = 'vertical', withHandle = true, className, ...props }, ref) {
    return (
        <div
            ref={ref}
            role="separator"
            aria-orientation={orientation}
            data-slot="resize-grip"
            className={cn(
                'quill-resizable__handle flex items-center justify-center',
                orientation === 'vertical' ? 'cursor-col-resize' : 'cursor-row-resize',
                className
            )}
            {...props}
        >
            {withHandle && <div />}
        </div>
    )
})

export { ResizableHandle, ResizablePanel, ResizablePanelGroup, ResizeGrip }
