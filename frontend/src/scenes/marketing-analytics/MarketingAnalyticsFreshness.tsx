import { IconClock, IconWarning } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

// Marketing analytics serves from precomputed data refreshed by the hourly warmer, so the numbers can
// trail live by up to ~2 hours. Past that the warmer is likely behind, so the badge switches to a warning.
const STALE_WARNING_HOURS = 2

export function MarketingAnalyticsFreshness({ computedAt }: { computedAt: string | null }): JSX.Element | null {
    if (!computedAt) {
        return null
    }

    const behindByHours = dayjs().diff(dayjs(computedAt), 'hour')
    const isBehind = behindByHours >= STALE_WARNING_HOURS

    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span>Marketing analytics refreshes about once an hour, so numbers can be up to 2 hours old.</span>
                    <div className="flex items-center gap-1">
                        <span>Data from</span>
                        <TZLabel time={computedAt} showPopover={false} />
                    </div>
                </div>
            }
        >
            <LemonButton
                icon={isBehind ? <IconWarning /> : <IconClock />}
                status={isBehind ? 'danger' : 'default'}
                type="secondary"
                size="small"
                // Informational only: keep it out of the tab order but labelled for screen readers.
                tabIndex={-1}
                aria-label="Marketing analytics data freshness"
                data-attr="marketing-analytics-freshness"
            >
                Updated hourly
            </LemonButton>
        </Tooltip>
    )
}
