import type { ReactNode } from 'react'

/** A titled card in the column next to the data pane, like the Filters and Marks cards. */
export function BIShelfCard({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-1 border-b px-2 py-1.5">
            <h3 className="m-0 text-xs font-semibold">{title}</h3>
            {children}
        </section>
    )
}
