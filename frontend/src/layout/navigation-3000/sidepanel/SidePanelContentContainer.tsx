import { useEffect, useRef } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

export function SidePanelContentContainer({
    className,
    contentClassName,
    children,
}: {
    className?: string
    contentClassName?: string
    children?: React.ReactNode
}): JSX.Element {
    // The actual scrollable element is the base-ui ScrollArea.Viewport inside ScrollableShadows,
    // not the outer Root. Stamp the data-attr on the Viewport via scrollRef so that consumers
    // walking up the DOM (e.g. ThreadAutoScroller) find the scrollable element rather than the
    // non-scrollable wrapper, which would cause scrollTo to silently no-op.
    const scrollRef = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        scrollRef.current?.setAttribute('data-attr', 'side-panel-content')
    }, [])

    return (
        <div className="scene-panel-content-container h-full">
            <ScrollableShadows
                direction="vertical"
                innerClassName="p-2 flex flex-col"
                contentClassName={contentClassName}
                styledScrollbars
                className={cn(
                    'h-full bg-surface-primary flex flex-col flex-1 overflow-y-auto focus-within:outline-none focus-within:ring-2 focus-within:ring-primary z-10',
                    className
                )}
                scrollRef={scrollRef}
            >
                {children}
            </ScrollableShadows>
        </div>
    )
}
