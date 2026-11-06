import { LemonCard } from '@posthog/lemon-ui'

export function LibrarySummaryPanel({
    icon,
    title,
    tag,
    actions,
    children,
}: {
    icon: JSX.Element
    title: string
    tag?: JSX.Element | null
    actions?: JSX.Element
    children: React.ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 p-3">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex min-w-0 items-center gap-2">
                    <span className="flex shrink-0 text-lg text-secondary">{icon}</span>
                    <h3 className="m-0 truncate text-base font-semibold">{title}</h3>
                    {tag}
                </div>
                {children}
            </div>
            {actions && <div className="flex shrink-0 flex-wrap gap-1">{actions}</div>}
        </LemonCard>
    )
}
