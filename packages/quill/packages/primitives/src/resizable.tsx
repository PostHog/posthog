import * as React from 'react'
import * as ResizablePrimitive from 'react-resizable-panels'

import { cn } from './lib/utils'

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
            className={cn(
                'relative flex w-px items-center justify-center bg-border ring-offset-background after:absolute after:inset-y-0 after:start-1/2 after:w-1 after:-translate-x-1/2 rtl:after:translate-x-1/2 hover:[&>div]:bg-primary/80 hover:after:bg-primary/10 focus-visible:after:bg-primary focus-visible:ring-ring focus-visible:outline-hidden aria-[orientation=horizontal]:h-px aria-[orientation=horizontal]:w-full aria-[orientation=horizontal]:after:start-0 aria-[orientation=horizontal]:after:h-1 aria-[orientation=horizontal]:after:w-full aria-[orientation=horizontal]:after:translate-x-0 rtl:aria-[orientation=horizontal]:after:-translate-x-0 aria-[orientation=horizontal]:after:-translate-y-1/2 [&[aria-orientation=horizontal]>div]:rotate-90',
                className
            )}
            {...props}
        >
            {withHandle && <div className="z-10 flex h-6 w-1 shrink-0 rounded-lg bg-border" />}
        </ResizablePrimitive.Separator>
    )
}

export { ResizableHandle, ResizablePanel, ResizablePanelGroup }
