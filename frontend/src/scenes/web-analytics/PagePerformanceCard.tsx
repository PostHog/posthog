import clsx from 'clsx'

import { PagePerformanceCardHeader } from './PagePerformanceCardHeader'

export interface PagePerformanceCardProps {
    title?: string
    footer?: React.ReactNode
    className?: string
    children: React.ReactNode
}

export function PagePerformanceCard({ title, footer, className, children }: PagePerformanceCardProps): JSX.Element {
    return (
        <div className={clsx('border rounded bg-surface-primary flex flex-col', className)}>
            {title ? <PagePerformanceCardHeader title={title} /> : null}
            <div className="flex flex-col flex-1 min-h-0">{children}</div>
            {footer ? <div className="border-t px-3 py-2 text-xs text-secondary">{footer}</div> : null}
        </div>
    )
}
