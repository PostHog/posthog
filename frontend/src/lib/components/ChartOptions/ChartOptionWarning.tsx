import { Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function ChartOptionWarning({ children }: { children: string }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Text size="xs" variant="destructive">
                {children}
            </Text>
        )
    }

    return <span className="text-xs text-danger">{children}</span>
}
