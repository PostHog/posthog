import type { ReactNode } from 'react'

/** A titled block in an evaluation drawer. Drawers separate these with dividers. */
export function EvaluationDrawerSection({
    title,
    subtitle,
    children,
}: {
    title: string
    subtitle?: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-col gap-0.5">
                <h4 className="m-0 text-sm font-semibold">{title}</h4>
                {subtitle && <span className="text-xs text-secondary">{subtitle}</span>}
            </div>
            {children}
        </section>
    )
}
