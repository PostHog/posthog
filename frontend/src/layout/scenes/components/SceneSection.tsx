import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

interface SceneSectionProps {
    title?: React.ReactNode
    description?: React.ReactNode
    isLoading?: boolean
    children: React.ReactNode
    className?: string
    hideTitleAndDescription?: boolean
    actions?: React.ReactNode
}

export function SceneSection({
    title,
    description,
    isLoading,
    children,
    className,
    hideTitleAndDescription,
    actions,
}: SceneSectionProps): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    // If not in new scene layout, we don't want to show anything new
    if (!newSceneLayout) {
        return (
            <div className={cn('scene-section--fallback flex flex-col gap-y-4', className)}>
                {!hideTitleAndDescription && (
                    <div className="flex">
                        <div className="flex flex-col gap-y-0 flex-1 justify-center">
                            <h2 className={cn('text-base font-semibold my-0 mb-1 max-w-prose', !description && 'mb-0')}>
                                {title}
                            </h2>
                            <p className="m-0">{description}</p>
                        </div>
                        {actions && <div className="flex gap-x-2 flex-none self-center">{actions}</div>}
                    </div>
                )}
                {children}
            </div>
        )
    }

    if (isLoading) {
        return (
            <div className={cn('flex flex-col gap-y-4', className)}>
                <div className="flex">
                    <div className="flex flex-col gap-y-0 flex-1 justify-center">
                        <h2 className={cn('text-base font-semibold my-0 mb-1 max-w-prose', !description && 'mb-0')}>
                            {title}
                        </h2>
                        {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
                    </div>
                    {actions && <div className="flex gap-x-2 flex-none self-center">{actions}</div>}
                </div>
                <WrappingLoadingSkeleton>{children}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div className={cn('scene-section--new-layout flex flex-col gap-y-4', className)}>
            {(title || description) && (
                <div className="flex gap-x-3">
                    <div className="flex flex-col gap-y-0 flex-1 justify-center">
                        <h2 className={cn('text-base font-semibold my-0 mb-1 max-w-prose', !description && 'mb-0')}>
                            {title}
                        </h2>
                        {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
                    </div>
                    {actions && <div className="flex gap-x-2 flex-none self-center">{actions}</div>}
                </div>
            )}
            {children}
        </div>
    )
}
