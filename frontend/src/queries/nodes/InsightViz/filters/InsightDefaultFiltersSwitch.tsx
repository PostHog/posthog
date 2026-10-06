import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductAnalyticsInsightQueryNode } from '~/queries/schema/schema-general'

type InsightDefaultFiltersSwitchProps = {
    query: ProductAnalyticsInsightQueryNode
    setQuery: (query: ProductAnalyticsInsightQueryNode) => void
    disabledReason?: string
}

export function InsightDefaultFiltersSwitch({
    query,
    setQuery,
    disabledReason,
}: InsightDefaultFiltersSwitchProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const hasDefaultFilters = (currentTeam?.default_filters_config?.filters ?? []).length > 0

    return (
        <div className="order-1 @lg:order-none">
            <LemonSwitch
                id="default-filters-switch"
                bordered
                checked={hasDefaultFilters ? !!query.applyDefaultFilters : false}
                onChange={(checked: boolean) => setQuery({ ...query, applyDefaultFilters: checked })}
                disabledReason={!hasDefaultFilters ? "You haven't set any default filters" : disabledReason}
                label={
                    <div className="flex items-center">
                        <span>Apply project default filters</span>
                        <LemonButton
                            icon={<IconGear />}
                            size="small"
                            noPadding
                            className="ml-1"
                            to={urls.settings('environment-customization', 'default-filters')}
                            targetBlank
                            hideExternalLinkIcon
                            tooltip="Configure default filters. Opens in a new tab."
                        />
                    </div>
                }
            />
        </div>
    )
}
