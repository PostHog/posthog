import { Text } from '@posthog/quill'

export function TodayHoverCardFact({
    label,
    children,
}: {
    label: string
    children: JSX.Element | string
}): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2 text-xs">
            <Text size="xs" variant="muted" render={<span />} className="w-16 shrink-0">
                {label}
            </Text>
            <span className="min-w-0 flex-1 truncate">{children}</span>
        </div>
    )
}
