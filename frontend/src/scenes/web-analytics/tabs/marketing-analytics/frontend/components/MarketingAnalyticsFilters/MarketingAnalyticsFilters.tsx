import { BindLogic } from 'kea'
import { useActions, useValues } from 'kea'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { Scene } from 'scenes/sceneTypes'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

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
                        <Shortcut
                            name="MarketingAnalyticsRefresh"
                            keybind={[keyBinds.refresh]}
                            intent="Refresh data"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <ReloadAll />
                        </Shortcut>
                        <ConversionGoalFilterButton />
                    </div>
                }
                right={
                    <>
                        <Shortcut
                            name="MarketingAnalyticsAddIntegration"
                            keybind={[keyBinds.new]}
                            intent="Add integration"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <AddIntegrationButton />
                        </Shortcut>
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
