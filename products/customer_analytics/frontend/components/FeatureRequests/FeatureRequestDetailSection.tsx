import type { ReactNode } from 'react'

export function FeatureRequestDetailSection({
    icon,
    title,
    children,
}: {
    icon: ReactNode
    title: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="flex shrink-0 items-center text-secondary [&_svg]:size-4">{icon}</span>
                    <h2 className="m-0 truncate text-sm font-semibold tracking-tight">{title}</h2>
                </div>
                <div className="h-px min-w-4 flex-1 bg-border-light" />
            </div>
            <div>{children}</div>
        </section>
    )
}
