import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

export function QuillLastRefreshText({ className }: { className?: string }): JSX.Element | null {
    const { effectiveLastRefresh } = useValues(dashboardLogic)

    if (!effectiveLastRefresh || dayjs().diff(dayjs(effectiveLastRefresh), 'hour') >= 24) {
        return null
    }

    return (
        <Text
            size="xs"
            variant="muted"
            render={<span className={cn('flex items-center gap-1 whitespace-nowrap', className)} />}
        >
            <span>Refreshed</span>
            <TZLabel time={effectiveLastRefresh} />
        </Text>
    )
}
