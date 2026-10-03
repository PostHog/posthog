import type { ReactNode } from 'react'

/** A titled card in the column next to the data pane, like the Filters and Marks cards. */
export function BIShelfCard({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-1.5 border-b p-2">
            <h3 className="m-0 text-sm font-semibold">{title}</h3>
            {children}
        </section>
    )
}
