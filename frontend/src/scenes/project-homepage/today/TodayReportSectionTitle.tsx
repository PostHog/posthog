import { Text } from '@posthog/quill'

export function TodayReportSectionTitle({ children }: { children: string }): JSX.Element {
    return (
        <Text size="base" weight="semibold" render={<h2 />}>
            {children}
        </Text>
    )
}
