import { IconClock, IconWarning } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

export function InsightFreshness({ lastRefresh }: { lastRefresh: string }): JSX.Element | null {
    if (!lastRefresh) {
        return null
    }

    const now = dayjs()
    const lastRefreshed = dayjs(lastRefresh)
    const diffHours = now.diff(lastRefreshed, 'hour')

    let icon: JSX.Element
    let color: string

    if (diffHours < 24) {
        icon = <IconClock />
        color = 'text-inherit'
    } else {
        icon = <IconWarning />
        color = 'text-danger'
    }

    return (
        <div className={`flex items-center gap-1 ${color}`}>
            <span className="text-tertiary text-xs opacity-30" aria-hidden="true">
                •
            </span>
            {icon} Computed <TZLabel time={lastRefresh} showPopover />
        </div>
    )
}
