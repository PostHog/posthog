import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

interface SceneStickyBarProps {
    children: React.ReactNode
    className?: string
    showBorderBottom?: boolean
}

export function SceneStickyBar({ children, className, showBorderBottom = true }: SceneStickyBarProps): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <div
            className={cn(
                'scene-sticky-bar sticky z-20 bg-primary top-[var(--breadcrumbs-height-compact)] space-y-2 py-2 ',
                newSceneLayout && 'top-[var(--scene-layout-header-height)] -mx-4 px-4 rounded-t-xl',
                className,
                showBorderBottom && 'border-b'
            )}
        >
            {children}
        </div>
    )
}
