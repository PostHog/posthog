import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

interface GuidedWizardSectionProps {
    title: ReactNode
    description?: ReactNode
    children?: ReactNode
    className?: string
    headerClassName?: string
    contentClassName?: string
    titleClassName?: string
    descriptionClassName?: string
    badge?: ReactNode
    actions?: ReactNode
}

export function GuidedWizardSection({
    title,
    description,
    children,
    className,
    headerClassName,
    contentClassName,
    titleClassName,
    descriptionClassName,
    badge,
    actions,
}: GuidedWizardSectionProps): JSX.Element {
    return (
        <section className={cn('space-y-3', className)}>
            <div className={cn('space-y-1', headerClassName)}>
                <div className="flex items-center justify-between gap-4">
                    <div className="flex min-w-0 items-center gap-2">
                        <h2 className={cn('m-0 text-xl font-semibold', titleClassName)}>{title}</h2>
                        {badge}
                    </div>
                    {actions}
                </div>
                {description ? <p className={cn('m-0 text-secondary', descriptionClassName)}>{description}</p> : null}
            </div>
            {children ? <div className={contentClassName}>{children}</div> : null}
        </section>
    )
}
