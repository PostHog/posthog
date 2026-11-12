import { BindLogic } from 'kea'
import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

import { AddIntegrationButton } from 'products/marketing_analytics/frontend/components/AddIntegrationButton'

import { MarketingAnalyticsTab, marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { ConversionGoalFilterButton } from './ConversionGoalFilterButton'
import { ConversionGoalModal } from './ConversionGoalModal'
import { IntegrationFilter } from './IntegrationFilter'
import { MarketingAnalyticsOptionsMenu } from './MarketingAnalyticsOptionsMenu'

export const MarketingAnalyticsFilters = ({
    tabs,
    searchOnly = false,
}: {
    tabs: JSX.Element
    searchOnly?: boolean
}): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { compareFilter, dateFilter, optionsOpen, isPerformanceTab, activeTab } = useValues(marketingAnalyticsLogic)
    const showMetricEditor = !searchOnly && activeTab !== MarketingAnalyticsTab.SEARCH_PERFORMANCE
    const showSearch = isPerformanceTab && !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]
    const { setCompareFilter, setDates, setOptionsOpen } = useActions(marketingAnalyticsLogic)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <FilterBar
                top={tabs}
                className="[&>div]:flex-wrap [&>div>div]:max-w-full [&>div>div>div]:min-w-0 [&>div>div>div>div]:max-w-full"
                left={
                    <div className="flex flex-wrap items-center gap-2 min-w-0 max-w-full">
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
                    </div>
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
                        <Popover
                            visible={optionsOpen}
                            onClickOutside={() => setOptionsOpen(false)}
                            placement="bottom-end"
                            overlay={
                                <MarketingAnalyticsOptionsMenu
                                    showMetricEditor={showMetricEditor}
                                    showIntegrations={!showSearch}
                                />
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
