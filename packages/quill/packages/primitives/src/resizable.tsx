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

export { ResizableHandle, ResizablePanel, ResizablePanelGroup }
