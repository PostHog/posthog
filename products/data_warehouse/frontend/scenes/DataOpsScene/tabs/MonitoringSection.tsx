import type { ReactNode } from 'react'

export function MonitoringSection({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="space-y-3">
            <div>
                <h2 className="mb-1">{title}</h2>
                <p className="mb-0 text-muted">{description}</p>
            </div>
            {children}
        </section>
    )
}
