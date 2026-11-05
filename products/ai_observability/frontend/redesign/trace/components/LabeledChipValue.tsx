import { ReactNode } from 'react'

export interface LabeledChipValueProps {
    label: string
    /** Replaces the visible label where an icon names the chip on its own; the label stays for screen readers. */
    icon?: JSX.Element
    children: ReactNode
}

// The label sits in its own tinted segment so our naming never reads as part of the user's value.
export function LabeledChipValue({ label, icon, children }: LabeledChipValueProps): JSX.Element {
    return (
        <span className="inline-flex min-w-0 items-center gap-1">
            <span className="-my-0.5 -ml-1 flex shrink-0 items-center self-stretch rounded-l-[calc(var(--radius)-1px)] border-r bg-surface-secondary px-1 text-secondary">
                {icon ? (
                    <>
                        <span className="flex text-xs">{icon}</span>
                        <span className="sr-only">{label}</span>
                    </>
                ) : (
                    label
                )}
            </span>
            {/* Monospace or vertically aligned values otherwise grow the line box a pixel past the tag's other chips. */}
            <span className="h-4 max-w-60 truncate">{children}</span>
        </span>
    )
}
