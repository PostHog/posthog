import { IconInfo } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

interface SceneSectionProps {
    title?: React.ReactNode
    description?: React.ReactNode
    titleHelper?: React.ReactNode
    isLoading?: boolean
    children: React.ReactNode
    className?: string
    hideTitleAndDescription?: boolean
    actions?: React.ReactNode
    /** sm = `<h3 className="text-sm">`, base = `<h2 className="text-base">` */
    titleSize?: 'sm' | 'base'
}

export function SceneSection({
    title,
    description,
    titleHelper,
    isLoading,
    children,
    className,
    actions,
    titleSize = 'base',
}: SceneSectionProps): JSX.Element {
    const Component = titleSize === 'sm' ? 'h3' : 'h2'
    const titleClassName = titleSize === 'sm' ? 'text-sm' : 'text-base'

    // If not in new scene layout, we don't want to show anything new

    if (isLoading) {
        return (
            <div className={cn('flex flex-col gap-y-4', className)}>
                <div className="flex">
                    <div className="flex flex-col gap-y-0 flex-1 justify-center">
                        <Component
                            className={cn(
                                'font-semibold my-0 mb-1 max-w-prose',
                                titleClassName,
                                !description && 'mb-0'
                            )}
                        >
                            {title}
                        </Component>
                        {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
                    </div>
                    {actions && <div className="flex gap-x-2 flex-none self-end">{actions}</div>}
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
                        <Component
                            className={cn(
                                'font-semibold my-0 mb-1 max-w-prose flex items-center gap-x-1',
                                titleClassName,
                                !description && 'mb-0'
                            )}
                        >
                            {title}

                            {titleHelper && (
                                <ButtonPrimitive tooltip={titleHelper} size="sm">
                                    <IconInfo className="size-4 text-sm text-secondary" />
                                </ButtonPrimitive>
                            )}
                        </Component>
                        {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
                    </div>
                    {actions && <div className="flex gap-x-2 flex-none self-end">{actions}</div>}
                </div>
            )}
            {children}
        </div>
    )
}
