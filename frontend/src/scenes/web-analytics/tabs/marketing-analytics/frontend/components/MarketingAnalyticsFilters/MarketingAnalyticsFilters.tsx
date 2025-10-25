import { BindLogic } from 'kea'
import { useActions, useValues } from 'kea'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { AddIntegrationButton } from './AddIntegrationButton'
import { IntegrationFilter } from './IntegrationFilter'

export const MarketingAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const { compareFilter, dateFilter } = useValues(marketingAnalyticsLogic)
    const { setCompareFilter, setDates } = useActions(marketingAnalyticsLogic)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <FilterBar
                top={tabs}
                left={<ReloadAll />}
                right={
                    <>
                        <AddIntegrationButton />
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
        </BindLogic>
    )
}
