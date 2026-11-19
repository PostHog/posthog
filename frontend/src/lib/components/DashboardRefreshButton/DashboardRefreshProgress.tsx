import { Spinner } from '@posthog/lemon-ui'
import { Spinner as QuillSpinner, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export interface DashboardRefreshProgressProps {
    completed: number
    /** Zero while the total is not known yet. */
    total: number
    initialLoad?: boolean
}

export function DashboardRefreshProgress({
    completed,
    total,
    initialLoad,
}: DashboardRefreshProgressProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const label = total
        ? `${initialLoad ? 'Loaded' : 'Refreshed'} ${completed} out of ${total}`
        : `${initialLoad ? 'Loading' : 'Refreshing'}…`

    if (todayRailNav) {
        return (
            <Text
                size="xs"
                variant="muted"
                render={<span role="status" className="flex items-center gap-1.5 whitespace-nowrap" />}
            >
                <QuillSpinner className="size-3" />
                <span translate="no">{label}</span>
            </Text>
        )
    }

    return (
        <span role="status" className="flex items-center gap-1 text-muted text-sm whitespace-nowrap">
            <Spinner textColored className="text-sm" />
            <span translate="no">{label}</span>
        </span>
    )
}
