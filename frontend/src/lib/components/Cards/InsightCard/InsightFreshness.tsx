import { IconClock, IconWarning } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function InsightFreshness({ lastRefresh }: { lastRefresh: string }): JSX.Element | null {
    if (!lastRefresh) {
        return null
    }

    const now = dayjs()
    const lastRefreshed = dayjs(lastRefresh)
    const diffHours = now.diff(lastRefreshed, 'hour')

    let icon: JSX.Element
    let status: 'default' | 'danger'

    if (diffHours < 24) {
        icon = <IconClock />
        status = 'default'
    } else {
        icon = <IconWarning />
        status = 'danger'
    }

    return (
        <Tooltip
            title={
                <div className="flex items-center gap-1">
                    <span>Computed</span>
                    <TZLabel time={lastRefresh} showPopover={false} />
                </div>
            }
        >
            <LemonButton icon={icon} size="small" noPadding status={status} data-attr="insight-card-freshness" />
        </Tooltip>
    )
}
