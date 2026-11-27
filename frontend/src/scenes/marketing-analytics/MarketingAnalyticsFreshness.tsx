import { IconClock } from '@posthog/icons'
import { Badge, Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function MarketingAnalyticsFreshness({
    latestDayComputedAt,
}: {
    latestDayComputedAt: string | null
}): JSX.Element | null {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!latestDayComputedAt) {
        return null
    }

    const explanation = (
        <div className="flex flex-col gap-1">
            <span>The numbers for the most recent day in this range were computed at this time or later.</span>
            <span>Ad spend also depends on when your data warehouse source last synced.</span>
            <TZLabel time={latestDayComputedAt} timestampStyle="absolute" showPopover={false} />
        </div>
    )

    if (todayRailNav) {
        return (
            <QuillTooltip>
                <TooltipTrigger render={<Badge tabIndex={0} data-attr="marketing-analytics-freshness" />}>
                    <IconClock />
                    <span>Computed&nbsp;</span>
                    <TZLabel time={latestDayComputedAt} showPopover={false} noStyles />
                </TooltipTrigger>
                <TooltipContent>{explanation}</TooltipContent>
            </QuillTooltip>
        )
    }

    return (
        <Tooltip title={explanation}>
            <LemonTag type="muted" icon={<IconClock />} data-attr="marketing-analytics-freshness">
                <span>Computed&nbsp;</span>
                <TZLabel time={latestDayComputedAt} showPopover={false} noStyles />
            </LemonTag>
        </Tooltip>
    )
}
