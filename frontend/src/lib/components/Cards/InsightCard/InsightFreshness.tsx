import { IconClock, IconWarning } from '@posthog/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dayjs } from 'lib/dayjs'
import { TZLabel } from 'lib/components/TZLabel'

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
        <Tooltip
            title={
                <div className="flex items-center gap-1">
                    <span>Computed</span>
                    <TZLabel time={lastRefresh} />
                </div>
            }
        >
            <div className={`flex items-center gap-1 ${color}`}>{icon}</div>
        </Tooltip>
    )
}
