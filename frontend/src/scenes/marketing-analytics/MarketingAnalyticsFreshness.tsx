import { IconClock } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function MarketingAnalyticsFreshness({
    latestDayComputedAt,
}: {
    latestDayComputedAt: string | null
}): JSX.Element | null {
    if (!latestDayComputedAt) {
        return null
    }

    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span>The numbers for the most recent day in this range were computed at this time or later.</span>
                    <span>Ad spend also depends on when your data warehouse source last synced.</span>
                    <TZLabel time={latestDayComputedAt} timestampStyle="absolute" showPopover={false} />
                </div>
            }
        >
            <LemonTag type="muted" icon={<IconClock />} data-attr="marketing-analytics-freshness">
                <span>Computed&nbsp;</span>
                <TZLabel time={latestDayComputedAt} showPopover={false} noStyles />
            </LemonTag>
        </Tooltip>
    )
}
