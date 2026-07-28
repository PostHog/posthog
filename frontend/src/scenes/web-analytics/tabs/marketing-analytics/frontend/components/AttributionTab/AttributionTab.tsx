import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { BREAKDOWN_LABELS, marketingAttributionLogic } from '../../logic/marketingAttributionLogic'
import { MarketingAnalyticsFilters } from '../MarketingAnalyticsFilters/MarketingAnalyticsFilters'
import { AttributionTable } from './AttributionTable'

// Ad group and ad are offered but disabled: they exist on the Dashboard's drill-down, so silently
// dropping them here reads as a bug. Events carry no ad identifier, so no model can credit them.
const UNATTRIBUTABLE_LEVELS = [
    { value: 'ad_group', label: 'Ad group' },
    { value: 'ad', label: 'Ad' },
]

const UNATTRIBUTABLE_REASON =
    "Ad platforms report cost per ad, but events don't carry an ad identifier, so conversions can't be credited to a specific ad."

export function AttributionTab(): JSX.Element {
    const { breakdownBy, excludeDirectTraffic, attributableGoals, selectedGoalId, query, attributionWindowDays } =
        useValues(marketingAttributionLogic)
    const { setBreakdownBy, setConversionGoalId, setExcludeDirectTraffic } = useActions(marketingAttributionLogic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)

    const settingsUrl = urls.settings('environment-marketing-analytics', 'marketing-settings')

    if (!attributableGoals.length) {
        return (
            <>
                <MarketingAnalyticsFilters tabs={<></>} />
                <LemonBanner
                    type="info"
                    className="mt-4"
                    action={{ children: 'Add a conversion goal', to: settingsUrl }}
                >
                    {conversion_goals?.length
                        ? "Your conversion goals all read from data warehouse tables, which attribution doesn't support yet. Add a goal based on an event or an action to compare attribution models."
                        : 'Attribution needs a conversion goal to credit. Add one to see how each model splits credit across your marketing.'}
                </LemonBanner>
            </>
        )
    }

    return (
        <>
            <MarketingAnalyticsFilters tabs={<></>} />
            <div className="mt-4 flex flex-col gap-4">
                <div className="flex flex-wrap items-center gap-4">
                    <div className="flex items-center gap-2">
                        <span className="text-secondary">Conversion goal</span>
                        <LemonSelect
                            size="small"
                            value={selectedGoalId}
                            onChange={(value) => value && setConversionGoalId(value)}
                            options={attributableGoals.map((goal: any) => ({
                                value: goal.conversion_goal_id,
                                label: goal.conversion_goal_name,
                            }))}
                        />
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-secondary">Break down by</span>
                        <LemonSelect
                            size="small"
                            value={breakdownBy}
                            onChange={(value) => value && setBreakdownBy(value)}
                            options={[
                                ...Object.values(MarketingAnalyticsAttributionBreakdown).map((level) => ({
                                    value: level,
                                    label: BREAKDOWN_LABELS[level],
                                })),
                                ...UNATTRIBUTABLE_LEVELS.map((level) => ({
                                    value: level.value as MarketingAnalyticsAttributionBreakdown,
                                    label: level.label,
                                    disabledReason: UNATTRIBUTABLE_REASON,
                                })),
                            ]}
                        />
                    </div>
                    <LemonSwitch
                        size="small"
                        checked={excludeDirectTraffic}
                        onChange={setExcludeDirectTraffic}
                        label={
                            <Tooltip title="Direct sessions stop counting as touchpoints, and the credit they would have taken is shared across the remaining ones.">
                                <span>Exclude direct traffic</span>
                            </Tooltip>
                        }
                    />
                    <div className="ml-auto flex items-center gap-1 text-secondary">
                        <span>{attributionWindowDays}-day attribution window</span>
                        <Link to={settingsUrl}>
                            <LemonButton size="xsmall" icon={<IconGear />} tooltip="Change the attribution window" />
                        </Link>
                    </div>
                </div>

                {query && <AttributionTable query={query} attachTo={marketingAnalyticsLogic} />}
            </div>
        </>
    )
}
