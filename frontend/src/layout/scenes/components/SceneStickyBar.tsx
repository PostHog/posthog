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
                'scene-sticky-bar @2xl/main-content:sticky z-20 bg-primary @2xl/main-content:top-[34px] space-y-2 py-2 -mx-4 px-4 rounded-t-xl',
                // Without a scene title section the bar pins itself. Sticky offsets start inside the
                // scroll container's padding, so pull it up by that padding to stop content showing above.
                !hasSceneTitleSection && '@2xl/main-content:-top-4',
                className,
                showBorderBottom && 'border-b'
            )}
        >
            {children}
        </div>
    )
}
