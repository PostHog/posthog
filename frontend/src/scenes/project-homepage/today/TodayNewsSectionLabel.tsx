import { Text } from '@posthog/quill'

export function TodayNewsSectionLabel({ children }: { children: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span />} className="font-semibold uppercase tracking-wider">
            {children}
        </Text>
    )
}
