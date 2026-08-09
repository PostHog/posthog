import { cn } from 'lib/utils/css-classes'

interface SceneStickyBarProps {
    children: React.ReactNode
    className?: string
    showBorderBottom?: boolean
    hasSceneTitleSection?: boolean
}

export function SceneStickyBar({
    children,
    className,
    showBorderBottom = true,
    hasSceneTitleSection = true,
}: SceneStickyBarProps): JSX.Element {
    return (
        <div
            className={cn(
                // z-40 keeps the bar above SceneTitleSection (z-30). A tall title can extend past
                // the reserved 34px offset and, when it wins the stacking order, its box covers the
                // bar's top row and swallows clicks on the filter controls.
                'scene-sticky-bar @2xl/main-content:sticky z-40 bg-primary @2xl/main-content:top-[34px] space-y-2 py-2 -mx-4 px-4 rounded-t-xl',
                !hasSceneTitleSection && '@2xl/main-content:top-0',
                className,
                showBorderBottom && 'border-b'
            )}
        >
            {children}
        </div>
    )
}
