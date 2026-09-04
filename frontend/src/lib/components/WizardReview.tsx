import type { ReactNode } from 'react'

export interface WizardReviewItem {
    label: string
    value: ReactNode
}

interface WizardReviewProps {
    items: WizardReviewItem[]
    notice?: ReactNode
    footer?: ReactNode
}

export function WizardReview({ items, notice, footer }: WizardReviewProps): JSX.Element {
    return (
        <div className="space-y-3">
            {notice}
            <div className="space-y-1.5 rounded border border-border bg-bg-light p-3 text-sm">
                {items.map(({ label, value }) => (
                    <div key={label} className="grid grid-cols-1 gap-1 sm:grid-cols-[13rem_minmax(0,1fr)] sm:gap-2">
                        <span className="text-muted">{label}</span>
                        <span className="font-medium">{value}</span>
                    </div>
                ))}
            </div>
            {footer}
        </div>
    )
}
