import { ReactNode } from 'react'

export interface LabeledChipValueProps {
    label: string
    children: ReactNode
}

// The label sits in its own tinted segment so our naming never reads as part of the user's value.
export function LabeledChipValue({ label, children }: LabeledChipValueProps): JSX.Element {
    return (
        <span className="inline-flex min-w-0 items-center gap-1">
            <span className="-my-0.5 -ml-1 flex shrink-0 items-center self-stretch rounded-l-[calc(var(--radius)-1px)] border-r bg-surface-secondary px-1 text-secondary">
                {label}
            </span>
            <span className="max-w-60 truncate">{children}</span>
        </span>
    )
}
