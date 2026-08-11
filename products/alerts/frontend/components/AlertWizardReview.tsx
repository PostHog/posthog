import type { ReactNode } from 'react'

export interface AlertWizardReviewItem {
    label: string
    value: ReactNode
}

interface AlertWizardReviewProps {
    items: AlertWizardReviewItem[]
    notice?: ReactNode
    footer?: ReactNode
}

export function AlertWizardReview({ items, notice, footer }: AlertWizardReviewProps): JSX.Element {
    return (
        <div className="space-y-3">
            {notice}
            <div className="space-y-1.5 rounded border border-border bg-bg-light p-3 text-sm">
                {items.map(({ label, value }) => (
                    <div key={label} className="flex gap-2">
                        <span className="min-w-24 max-w-36 shrink-0 text-muted">{label}</span>
                        <span className="font-medium">{value}</span>
                    </div>
                ))}
            </div>
            {footer}
        </div>
    )
}
