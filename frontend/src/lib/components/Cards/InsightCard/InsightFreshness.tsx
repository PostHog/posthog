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
            <LemonButton
                icon={icon}
                noPadding
                status={status}
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
