import { useValues } from 'kea'

import { Spinner, Text } from '@posthog/quill'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

export function QuillDashboardRefreshProgress(): JSX.Element {
    const { refreshMetrics, dashboardLoadData } = useValues(dashboardLogic)
    const isInitialLoad =
        dashboardLoadData?.action === 'initial_load' || dashboardLoadData?.action === 'initial_load_with_variables'

    const label = refreshMetrics.total
        ? `${isInitialLoad ? 'Loaded' : 'Refreshed'} ${refreshMetrics.completed} out of ${refreshMetrics.total}`
        : `${isInitialLoad ? 'Loading' : 'Refreshing'}…`

    return (
        <Text
            size="xs"
            variant="muted"
            render={<span role="status" className="flex items-center gap-1.5 whitespace-nowrap" />}
        >
            <Spinner className="size-3" />
            <span translate="no">{label}</span>
        </Text>
    )
}
