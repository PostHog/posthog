import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

interface GuidedWizardStepLayoutProps {
    children: ReactNode
    className?: string
}

export function GuidedWizardStepLayout({ children, className }: GuidedWizardStepLayoutProps): JSX.Element {
    return <div className={cn('space-y-5', className)}>{children}</div>
}

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

interface GuidedWizardPanelProps {
    children: ReactNode
    className?: string
}

export function GuidedWizardPanel({ children, className }: GuidedWizardPanelProps): JSX.Element {
    return <div className={cn('rounded-lg border border-border bg-surface-primary p-3', className)}>{children}</div>
}

interface GuidedWizardDividerSectionProps {
    title?: ReactNode
    description?: ReactNode
    children: ReactNode
    className?: string
    contentClassName?: string
    titleClassName?: string
    descriptionClassName?: string
}

export function GuidedWizardDividerSection({
    title,
    description,
    children,
    className,
    contentClassName,
    titleClassName,
    descriptionClassName,
}: GuidedWizardDividerSectionProps): JSX.Element {
    return (
        <section className={cn('border-t border-border pt-5', className)}>
            {(title || description) && (
                <div className="space-y-1">
                    {title ? <h2 className={cn('m-0 text-xl font-semibold', titleClassName)}>{title}</h2> : null}
                    {description ? (
                        <p className={cn('m-0 text-secondary', descriptionClassName)}>{description}</p>
                    ) : null}
                </div>
            )}
            <div className={cn(title || description ? 'mt-4' : undefined, contentClassName)}>{children}</div>
        </section>
    )
}
