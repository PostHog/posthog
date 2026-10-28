import { BindLogic } from 'kea'
import { useActions, useValues } from 'kea'

import { IconComment, IconGear, IconPencil } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, Popover } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

import { AddIntegrationButton } from 'products/marketing_analytics/frontend/components/AddIntegrationButton'
import { overviewMetricsLogic } from 'products/marketing_analytics/frontend/overview/overviewMetricsLogic'

import { MarketingAnalyticsTab, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { ConversionGoalFilterButton } from './ConversionGoalFilterButton'
import { ConversionGoalModal } from './ConversionGoalModal'
import { IntegrationFilter } from './IntegrationFilter'

export const MarketingAnalyticsFilters = ({
    tabs,
    searchOnly = false,
}: {
    tabs: JSX.Element
    searchOnly?: boolean
}): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        compareFilter,
        dateFilter,
        shouldFilterTestAccounts,
        optionsOpen,
        isPerformanceTab,
        includeConversionGoals,
        canToggleConversionGoals,
        activeTab,
    } = useValues(marketingAnalyticsLogic)
    const { openEditor } = useActions(overviewMetricsLogic({ viewKey: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }))
    const showMetricEditor = !searchOnly && activeTab !== MarketingAnalyticsTab.SEARCH_PERFORMANCE
    const showSearch = isPerformanceTab && !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]
    const { currentTeamLoading } = useValues(teamLogic)
    const { setCompareFilter, setDates, updateFilterTestAccounts, setOptionsOpen, setAdPerformanceConversionGoals } =
        useActions(marketingAnalyticsLogic)
    // The setting lives on the project, so flipping it changes what everyone sees.
    const editRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <FilterBar
                top={tabs}
                left={
                    <>
                        <Shortcut
                            name="MarketingAnalyticsRefresh"
                            keybind={[keyBinds.refresh]}
                            intent="Refresh data"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <ReloadAll iconOnly />
                        </Shortcut>
                        <DateFilter
                            allowTimePrecision
                            dateFrom={dateFilter.dateFrom}
                            dateTo={dateFilter.dateTo}
                            onChange={setDates}
                        />
                        <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                        {!searchOnly && <ConversionGoalFilterButton />}
                        {(showSearch || searchOnly) && <IntegrationFilter />}
                    </>
                }
                right={
                    <>
                        {/* The bar lays these out right to left, so source order runs from the far right. */}
                        <Shortcut
                            name="MarketingAnalyticsAddIntegration"
                            keybind={[keyBinds.new]}
                            intent="Add integration"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <AddIntegrationButton />
                        </Shortcut>
                        {/* The id is how the in-app feedback survey finds this button. */}
                        {!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING] && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconComment />}
                                id="marketing-analytics-feedback-button"
                                data-attr="marketing-analytics-feedback-button"
                            >
                                Share your feedback
                            </LemonButton>
                        )}
                        <Popover
                            visible={optionsOpen}
                            onClickOutside={() => setOptionsOpen(false)}
                            placement="bottom-end"
                            overlay={
                                // Ordered by how often they get touched, so the rarely-changed
                                // project setting sits last.
                                <div className="flex w-80 max-w-[90vw] flex-col gap-4 p-3">
                                    {showMetricEditor && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            fullWidth
                                            icon={<IconPencil />}
                                            onClick={() => {
                                                setOptionsOpen(false)
                                                openEditor()
                                            }}
                                            data-attr="marketing-configure-metrics"
                                        >
                                            Edit top-line metrics
                                        </LemonButton>
                                    )}
                                    {canToggleConversionGoals && (
                                        <div>
                                            <div className="text-muted mb-2 text-xs font-semibold uppercase">
                                                Conversions
                                            </div>
                                            <LemonSwitch
                                                bordered
                                                fullWidth
                                                label="Include conversion goals"
                                                checked={includeConversionGoals}
                                                onChange={setAdPerformanceConversionGoals}
                                                data-attr="marketing-ad-performance-conversion-goals"
                                            />
                                        </div>
                                    )}
                                    {!showSearch && (
                                        <div>
                                            <div className="text-muted mb-2 text-xs font-semibold uppercase">
                                                Integrations
                                            </div>
                                            <IntegrationFilter />
                                        </div>
                                    )}
                                    <LemonDivider className="my-0" />
                                    {/* Only the event side honors this: ad spend comes from the platforms. */}
                                    <TestAccountFilterSwitch
                                        fullWidth
                                        checked={shouldFilterTestAccounts}
                                        onChange={updateFilterTestAccounts}
                                        disabledReason={
                                            editRestrictionReason ?? (currentTeamLoading ? 'Saving…' : undefined)
                                        }
                                    />
                                </div>
                            }
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconGear />}
                                onClick={() => setOptionsOpen(!optionsOpen)}
                                data-attr="marketing-analytics-options"
                            >
                                Options
                            </LemonButton>
                        </Popover>
                    </>
                }
            />
            <ConversionGoalModal />
        </BindLogic>
    )
}
