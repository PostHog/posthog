import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { urls } from 'scenes/urls'

import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { BREAKDOWN_LABELS, marketingAttributionLogic } from '../../logic/marketingAttributionLogic'
import { AttributionTable } from './AttributionTable'

// Ad group and ad are offered but disabled: they exist on the Dashboard's drill-down, so silently
// dropping them here reads as a bug. Events carry no ad identifier, so no model can credit them.
const UNATTRIBUTABLE_LEVELS = [
    { value: 'ad_group', label: 'Ad group' },
    { value: 'ad', label: 'Ad' },
]

const UNATTRIBUTABLE_REASON =
    "Ad platforms report cost per ad, but events don't carry an ad identifier, so conversions can't be credited to a specific ad."

const LOOKBACK_PRESETS_DAYS = [7, 14, 30, 60, 90, 180]

export function AttributionTab(): JSX.Element {
    const {
        breakdownBy,
        excludeDirectTraffic,
        attributableGoals,
        selectedGoalId,
        query,
        attributionWindowDays,
        effectiveLookbackDays,
        effectiveAllowMultipleConversions,
        activeOptionCount,
    } = useValues(marketingAttributionLogic)
    const {
        setBreakdownBy,
        setConversionGoalId,
        setExcludeDirectTraffic,
        setLookbackWindowDays,
        setAllowMultipleConversionsPerVisitor,
    } = useActions(marketingAttributionLogic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { dateFilter } = useValues(marketingAnalyticsLogic)
    const { setDates } = useActions(marketingAnalyticsLogic)

    const settingsUrl = urls.settings('environment-marketing-analytics', 'marketing-settings')

    if (!attributableGoals.length) {
        return (
            <LemonBanner type="info" className="mt-4" action={{ children: 'Add a conversion goal', to: settingsUrl }}>
                {conversion_goals?.length
                    ? "Your conversion goals all read from data warehouse tables, which attribution doesn't support yet. Add a goal based on an event or an action to compare attribution models."
                    : 'Attribution needs a conversion goal to credit. Add one to see how each model splits credit across your marketing.'}
            </LemonBanner>
        )
    }

    const lookbackOptions = [...new Set([...LOOKBACK_PRESETS_DAYS, attributionWindowDays])]
        .sort((a, b) => a - b)
        .map((days) => ({
            value: days,
            label: days === attributionWindowDays ? `${days} days (default)` : `${days} days`,
        }))

    return (
        <div className="flex flex-col">
            <FilterBar
                showBorderBottom
                left={
                    <div className="flex flex-wrap items-center gap-4">
                        <div className="flex items-center gap-2">
                            <span className="text-secondary">Conversion goal</span>
                            <LemonSelect
                                size="small"
                                value={selectedGoalId}
                                onChange={(value) => value && setConversionGoalId(value)}
                                options={attributableGoals.map((goal) => ({
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
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        sideIcon={<IconChevronDown />}
                                        data-attr="marketing-attribution-options"
                                    />
                                }
                            >
                                {activeOptionCount > 0 ? `Options (${activeOptionCount})` : 'Options'}
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start" className="max-w-100 min-w-fit">
                                <DropdownMenuCheckboxItem
                                    checked={excludeDirectTraffic}
                                    onCheckedChange={setExcludeDirectTraffic}
                                    closeOnClick={false}
                                    data-attr="marketing-attribution-exclude-direct"
                                >
                                    Exclude direct traffic
                                </DropdownMenuCheckboxItem>
                                <DropdownMenuCheckboxItem
                                    checked={effectiveAllowMultipleConversions}
                                    onCheckedChange={setAllowMultipleConversionsPerVisitor}
                                    closeOnClick={false}
                                    data-attr="marketing-attribution-allow-multiple-conversions"
                                >
                                    Count repeat conversions
                                </DropdownMenuCheckboxItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                }
                right={
                    <>
                        <div className="flex items-center gap-2">
                            <Tooltip title="How far back before each conversion a touchpoint can earn credit. The default comes from your marketing settings.">
                                <span className="text-secondary">Lookback window</span>
                            </Tooltip>
                            <LemonSelect
                                size="small"
                                value={effectiveLookbackDays}
                                onChange={(value) =>
                                    // Picking the default stores null, so a later settings change flows through.
                                    value && setLookbackWindowDays(value === attributionWindowDays ? null : value)
                                }
                                options={lookbackOptions}
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <Tooltip title="Conversions in this period get credited. Their touchpoints can come from up to the lookback window before it.">
                                <span className="text-secondary">Conversion period</span>
                            </Tooltip>
                            <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                        </div>
                    </>
                }
            />
            <div className="mt-4 flex flex-col gap-4 pb-8">
                {query && <AttributionTable query={query} attachTo={marketingAnalyticsLogic} />}
            </div>
        </div>
    )
}
