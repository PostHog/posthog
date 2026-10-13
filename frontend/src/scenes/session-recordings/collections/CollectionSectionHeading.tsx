export function CollectionSectionHeading({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex items-center gap-3 px-3 py-1.5 border-b bg-surface-tertiary dark:bg-surface-secondary flex-wrap">
            <span className="text-xs font-semibold uppercase tracking-wide text-secondary">{title}</span>
            <span className="text-xs text-muted">{description}</span>
            {children ? <div className="ml-auto flex items-center gap-2 flex-wrap">{children}</div> : null}
        </div>
    )
}
