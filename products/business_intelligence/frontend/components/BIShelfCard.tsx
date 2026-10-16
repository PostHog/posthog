import type { ReactNode } from 'react'

/** A titled card in the column next to the data pane, like the Filters and Marks cards. */
export function BIShelfCard({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-1 border-b bg-surface-primary px-2 py-2">
            <h3 className="m-0 pb-1 text-xs font-semibold">{title}</h3>
            {children}
        </section>
    )
}
