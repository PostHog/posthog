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
                'scene-sticky-bar @2xl/main-content:sticky z-20 bg-primary @2xl/main-content:top-[calc(var(--scene-layout-header-height)+var(--scene-title-section-height))] space-y-2 py-2 -mx-4 px-4 rounded-t-xl',
                !hasSceneTitleSection && '@2xl/main-content:top-[var(--scene-layout-header-height)]',
                className,
                showBorderBottom && 'border-b'
            )}
        >
            {children}
        </div>
    )
}
