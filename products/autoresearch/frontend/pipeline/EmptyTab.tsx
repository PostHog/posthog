/** Shared empty-state block: an icon, a headline, supporting copy, and an optional CTA. */
export function EmptyTab({
    icon,
    title,
    children,
    cta,
}: {
    icon: JSX.Element
    title: string
    children: React.ReactNode
    cta?: JSX.Element
}): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center gap-2 border border-dashed rounded p-8 text-muted">
            <span className="text-2xl text-secondary">{icon}</span>
            <div className="text-sm font-semibold text-default">{title}</div>
            <div className="text-sm max-w-prose">{children}</div>
            {cta}
        </div>
    )
}
