import { ReactNode } from 'react'

interface DetailSectionProps {
    icon: ReactNode
    title: string
    rightSlot?: ReactNode
    children: ReactNode
}

/** Prominent content section with a spanning divider, used for the main column (Summary, Evidence). */
export function DetailSection({ icon, title, rightSlot, children }: DetailSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0 cursor-default select-none">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="shrink-0 text-secondary">{icon}</span>
                    <span className="truncate font-semibold text-sm text-primary">{title}</span>
                </div>
                <div className="h-px min-w-4 flex-1 bg-border-light" />
                {rightSlot && <div className="shrink-0">{rightSlot}</div>}
            </div>
            <div>{children}</div>
        </div>
    )
}

interface RightColumnSectionProps {
    icon: ReactNode
    title: string
    rightSlot?: ReactNode
    children: ReactNode
}

/**
 * Slim caption header used by sections in the detail-view right column (Runs, Reviewers).
 * Lighter than `DetailSection` so the side column reads as supporting detail.
 */
export function RightColumnSection({ icon, title, rightSlot, children }: RightColumnSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2 cursor-default select-none text-tertiary">
                <div className="flex items-center gap-2">
                    <span className="shrink-0">{icon}</span>
                    <span className="font-medium text-[0.6875rem] uppercase tracking-wide">{title}</span>
                </div>
                {rightSlot && <div className="shrink-0">{rightSlot}</div>}
            </div>
            <div>{children}</div>
        </div>
    )
}
