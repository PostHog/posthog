import { ReactNode } from 'react'

export function PagePerformanceCardHeader({ title, actions }: { title: string; actions?: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
            <h3 className="m-0 text-sm font-semibold">{title}</h3>
            {actions}
        </div>
    )
}
