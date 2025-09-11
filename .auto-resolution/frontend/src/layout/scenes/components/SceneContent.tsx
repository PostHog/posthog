import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

export function SceneContent({
    children,
    className,
    forceNewSpacing,
}: {
    children: React.ReactNode
    className?: string
    forceNewSpacing?: boolean
}): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <div className={cn('scene-content flex flex-col', (newSceneLayout || forceNewSpacing) && 'gap-y-4', className)}>
            {children}
        </div>
    )
}
