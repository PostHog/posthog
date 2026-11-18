import posthog from 'posthog-js'

import { IconDashboard } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

export function SavedInsightsNotOnAnyDashboardFilter({
    notOnAnyDashboard,
    setFilters,
    borderless,
}: {
    notOnAnyDashboard: boolean | undefined | null
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    borderless: boolean
}): JSX.Element {
    return (
        <Tooltip
            title={
                <div>
                    <p>
                        Hide insights that are already attached to a dashboard, so you can focus on insights that aren't
                        on any dashboard yet.
                    </p>
                    <p className="mb-0">
                        Useful for cleaning up forgotten insights or finding ones worth promoting to a dashboard.
                    </p>
                </div>
            }
            placement="top"
        >
            <LemonButton
                type="secondary"
                status={borderless && !notOnAnyDashboard ? 'alt' : 'default'}
                active={notOnAnyDashboard || false}
                onClick={() => {
                    setFilters({ notOnAnyDashboard: !notOnAnyDashboard })
                    posthog.capture('saved insights filtered', {
                        filter_type: 'not_on_any_dashboard',
                        value: !notOnAnyDashboard,
                    })
                }}
                size="small"
                icon={<IconDashboard />}
            >
                <span>Not on any dashboard: </span>
                <LemonSwitch checked={notOnAnyDashboard || false} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
