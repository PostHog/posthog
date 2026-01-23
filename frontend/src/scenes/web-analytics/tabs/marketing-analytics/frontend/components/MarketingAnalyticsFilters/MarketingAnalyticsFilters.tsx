import { BindLogic } from 'kea'
import { useActions, useValues } from 'kea'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { Scene } from 'scenes/sceneTypes'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { AddIntegrationButton } from './AddIntegrationButton'
import { ConversionGoalFilterButton } from './ConversionGoalFilterButton'
import { ConversionGoalModal } from './ConversionGoalModal'
import { IntegrationFilter } from './IntegrationFilter'

export const MarketingAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const { compareFilter, dateFilter } = useValues(marketingAnalyticsLogic)
    const { setCompareFilter, setDates } = useActions(marketingAnalyticsLogic)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <FilterBar
                top={tabs}
                left={
                    <div className="flex items-center gap-4">
                        <AppShortcut
                            name="MarketingAnalyticsRefresh"
                            keybind={[keyBinds.refresh]}
                            intent="Refresh data"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <ReloadAll />
                        </AppShortcut>
                        <ConversionGoalFilterButton />
                    </div>
                }
                right={
                    <>
                        <AppShortcut
                            name="MarketingAnalyticsAddIntegration"
                            keybind={[keyBinds.new]}
                            intent="Add integration"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <AddIntegrationButton />
                        </AppShortcut>
                        <IntegrationFilter />
                        <DateFilter
                            allowTimePrecision
                            dateFrom={dateFilter.dateFrom}
                            dateTo={dateFilter.dateTo}
                            onChange={setDates}
                        />
                        <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                    </>
                }
            />
            <ConversionGoalModal />
        </BindLogic>
    )
}
