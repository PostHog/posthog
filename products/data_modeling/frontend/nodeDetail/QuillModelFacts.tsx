import type { ReactNode } from 'react'

export function QuillModelFacts({ label, children }: { label?: string; children: ReactNode }): JSX.Element {
    return (
        <dl className="m-0 flex flex-wrap gap-x-10 gap-y-3" aria-label={label}>
            {children}
        </dl>
    )
}
