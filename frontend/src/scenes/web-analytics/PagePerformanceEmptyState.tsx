import clsx from 'clsx'

export interface PagePerformanceEmptyStateProps {
    title: string
    /** One or two short lines saying why this is empty and what to do next. */
    children: React.ReactNode
    action?: React.ReactNode
    className?: string
}

export function PagePerformanceEmptyState({
    title,
    children,
    action,
    className,
}: PagePerformanceEmptyStateProps): JSX.Element {
    return (
        <div
            className={clsx(
                'border rounded bg-surface-primary flex flex-col items-center gap-2 px-6 py-10 text-center',
                className
            )}
        >
            <h3 className="m-0 text-base font-semibold">{title}</h3>
            <div className="flex flex-col gap-1 max-w-140 text-sm text-secondary">{children}</div>
            {action ? <div className="mt-2 flex items-center gap-2">{action}</div> : null}
        </div>
    )
}
