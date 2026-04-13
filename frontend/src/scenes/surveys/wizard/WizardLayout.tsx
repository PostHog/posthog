import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

interface WizardStepLayoutProps {
    children: ReactNode
    className?: string
}

export function WizardStepLayout({ children, className }: WizardStepLayoutProps): JSX.Element {
    return <div className={cn('space-y-5', className)}>{children}</div>
}

interface WizardSectionProps {
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

export function WizardSection({
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
}: WizardSectionProps): JSX.Element {
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

interface WizardPanelProps {
    children: ReactNode
    className?: string
}

export function WizardPanel({ children, className }: WizardPanelProps): JSX.Element {
    return <div className={cn('rounded-lg border border-border bg-surface-primary p-3', className)}>{children}</div>
}

interface WizardDividerSectionProps {
    title?: ReactNode
    description?: ReactNode
    children: ReactNode
    className?: string
    contentClassName?: string
    titleClassName?: string
    descriptionClassName?: string
}

export function WizardDividerSection({
    title,
    description,
    children,
    className,
    contentClassName,
    titleClassName,
    descriptionClassName,
}: WizardDividerSectionProps): JSX.Element {
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
