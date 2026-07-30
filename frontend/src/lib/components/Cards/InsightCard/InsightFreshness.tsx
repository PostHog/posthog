import { IconClock } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function InsightFreshness({ lastRefresh }: { lastRefresh: string }): JSX.Element | null {
    if (!lastRefresh) {
        return null
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
            <LemonButton
                // Always a neutral clock: age alone isn't a failure, and an error affordance here
                // reads as "this tile broke" even when the result is perfectly valid.
                icon={<IconClock />}
                noPadding
                // Indicator is informational only — keep it out of the tab order, but labelled for screen readers.
                tabIndex={-1}
                aria-label="Last computed time"
                data-attr="insight-card-freshness"
                // Render the glyph at the surrounding heading's text size (as the bare icon did);
                // LemonButton's default icon sizing made the clock noticeably larger than its row.
                style={{ '--lemon-button-font-size': '1em', '--lemon-button-icon-size': '1em' } as React.CSSProperties}
            />
        </Tooltip>
    )
}
