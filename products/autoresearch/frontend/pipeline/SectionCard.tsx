import { LemonCard } from '@posthog/lemon-ui'

/** The white surface for one section of a detail tab: an optional title row with a control on the right, then the body. */
export function SectionCard({
    title,
    description,
    actions,
    children,
}: {
    title?: React.ReactNode
    description?: React.ReactNode
    actions?: React.ReactNode
    children?: React.ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-3 min-w-0">
            {(title || description || actions) && (
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 space-y-1">
                        {title && <h3 className="flex items-center gap-2 text-sm font-semibold mb-0">{title}</h3>}
                        {description && <div className="text-xs text-muted">{description}</div>}
                    </div>
                    {actions}
                </div>
            )}
            {children}
        </LemonCard>
    )
}
