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
                    <div key={label} className="grid grid-cols-[13rem_minmax(0,1fr)] gap-2">
                        <span className="text-muted">{label}</span>
                        <span className="font-medium">{value}</span>
                    </div>
                ))}
            </div>
            {footer}
        </div>
    )
}
