import { LemonCard } from '@posthog/lemon-ui'

export function UsageStat({ label, value, caption }: { label: string; value: string; caption: string }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex min-w-0 flex-col gap-1 p-3">
            <span className="text-sm text-secondary">{label}</span>
            <span className="text-2xl font-semibold" translate="no">
                {value}
            </span>
            <span className="text-xs text-muted">{caption}</span>
        </LemonCard>
    )
}
