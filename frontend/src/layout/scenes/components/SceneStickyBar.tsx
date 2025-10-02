import { cn } from 'lib/utils/css-classes'

interface SceneStickyBarProps {
    children: React.ReactNode
    className?: string
    showBorderBottom?: boolean
}

export function SceneStickyBar({ children, className, showBorderBottom = true }: SceneStickyBarProps): JSX.Element {
    return (
        <div
            className={cn(
                'scene-sticky-bar sticky z-20 bg-primary top-[var(--breadcrumbs-height-compact)] space-y-2 py-2 ',
                'top-[var(--scene-layout-header-height)] -mx-4 px-4 rounded-t-xl',
                className,
                showBorderBottom && 'border-b'
            )}
        >
            {children}
        </div>
    )
}
