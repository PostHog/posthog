import { BindLogic, useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSelect, LemonSwitch, Popover } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { urls } from 'scenes/urls'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    BREAKDOWN_LABELS,
    MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID,
    marketingAttributionLogic,
    unattributedTooltip,
} from '../../logic/marketingAttributionLogic'
import { AttributionTable } from './AttributionTable'
import { ConversionPaths } from './ConversionPaths'

// Offered but disabled: they exist on the Dashboard's drill-down, so dropping them silently reads as
// a bug, but events carry no ad identifier for any model to credit.
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
        excludeUnattributed,
        attributableGoals,
        selectedGoalId,
        query,
        pathsQuery,
        attribution_window_days,
        effectiveLookbackDays,
        effectiveAllowMultipleConversions,
        optionsOpen,
    } = useValues(marketingAttributionLogic)
    const {
        setBreakdownBy,
        setConversionGoalId,
        setExcludeDirectTraffic,
        setExcludeUnattributed,
        setLookbackWindowDays,
        setAllowMultipleConversionsPerVisitor,
        setOptionsOpen,
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

    const lookbackOptions = [...new Set([...LOOKBACK_PRESETS_DAYS, attribution_window_days])]
        .sort((a, b) => a - b)
        .map((days) => ({
            value: days,
            label: days === attribution_window_days ? `${days} days (default)` : `${days} days`,
        }))

    const optionsContent = (
        <div className="flex w-80 max-w-[90vw] flex-col gap-4 p-3">
            <div>
                <div className="text-muted mb-2 text-xs font-semibold uppercase">Conversion period</div>
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                <div className="text-muted mt-1 text-xs">
                    Conversions in this period get credited. Their touchpoints can come from earlier.
                </div>
            </div>
            <div>
                <div className="text-muted mb-2 text-xs font-semibold uppercase">Lookback window</div>
                <LemonSelect
                    fullWidth
                    value={effectiveLookbackDays}
                    onChange={(value) =>
                        // Picking the default stores null, so a later settings change flows through.
                        value && setLookbackWindowDays(value === attribution_window_days ? null : value)
                    }
                    options={lookbackOptions}
                />
                <div className="text-muted mt-1 text-xs">
                    How far back before each conversion a touchpoint can earn credit. The default comes from your
                    marketing settings.
                </div>
            </div>
            <LemonDivider className="my-0" />
            <LemonSwitch
                fullWidth
                checked={excludeDirectTraffic}
                onChange={setExcludeDirectTraffic}
                label="Exclude direct traffic"
                tooltip="Direct sessions stop counting as touchpoints, and the credit they would have taken is shared across the remaining ones."
                data-attr="marketing-attribution-exclude-direct"
            />
            <LemonSwitch
                fullWidth
                checked={excludeUnattributed}
                onChange={setExcludeUnattributed}
                label="Exclude unattributed traffic"
                tooltip={unattributedTooltip(breakdownBy)}
                data-attr="marketing-attribution-exclude-unattributed"
            />
            <LemonSwitch
                fullWidth
                checked={effectiveAllowMultipleConversions}
                onChange={setAllowMultipleConversionsPerVisitor}
                label="Count repeat conversions"
                tooltip="Count every conversion a person makes, not just their first. Turning this on can push the rate columns above one conversion per visitor, so they're shown as a ratio instead of a percentage."
                data-attr="marketing-attribution-allow-multiple-conversions"
            />
        </div>
    )

    return (
        // Rebinds the collection inside the tab, shadowing the scene-level binding on purpose: the
        // refresh button reloads the attribution queries, not the dashboard tiles.
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID }}>
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
                        </div>
                    }
                    right={
                        <div className="flex items-center gap-2">
                            <ReloadAll iconOnly />
                            <Popover
                                visible={optionsOpen}
                                onClickOutside={() => setOptionsOpen(false)}
                                placement="bottom-end"
                                overlay={optionsContent}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconGear />}
                                    onClick={() => setOptionsOpen(!optionsOpen)}
                                    data-attr="marketing-attribution-options"
                                >
                                    Options
                                </LemonButton>
                            </Popover>
                        </div>
                    }
                />
                <div className="mt-4 flex flex-col gap-4 pb-8">
                    {query && <AttributionTable query={query} attachTo={marketingAnalyticsLogic} />}
                    {pathsQuery && <ConversionPaths query={pathsQuery} attachTo={marketingAnalyticsLogic} />}
                </div>
            </div>
        </BindLogic>
    )
}
