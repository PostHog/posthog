import { LemonLabel } from '@posthog/lemon-ui'

export function PartnerBillingDetail({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <LemonLabel>{label}</LemonLabel>
            <div className="break-words">{children}</div>
        </div>
    )
}
