import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

export function SidePanelContentContainer({
    className,
    children,
}: {
    className?: string
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div className="scene-panel-content-container h-full">
            <ScrollableShadows
                direction="vertical"
                innerClassName="p-2 flex flex-col"
                styledScrollbars
                className={cn(
                    'h-full bg-surface-primary flex flex-col flex-1 overflow-y-auto focus-within:outline-none focus-within:ring-2 focus-within:ring-primary z-10',
                    className
                )}
                data-attr="side-panel-content"
            >
                {children}
            </ScrollableShadows>
        </div>
    )
}
