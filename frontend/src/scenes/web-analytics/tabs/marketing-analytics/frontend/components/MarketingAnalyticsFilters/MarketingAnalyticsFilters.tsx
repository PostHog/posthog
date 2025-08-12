import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { BindLogic } from 'kea'

export const MarketingAnalyticsFilters = (): JSX.Element => {
    const { compareFilter, dateFilter } = useValues(marketingAnalyticsLogic)
    const { setCompareFilter, setDates } = useActions(marketingAnalyticsLogic)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <div className="flex flex-col md:flex-row md:justify-between gap-2">
                <ReloadAll />
                <div className="flex flex-row gap-2 items-center">
                    <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                    <DateFilter
                        allowTimePrecision
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={setDates}
                    />
                </div>
            </div>
        </BindLogic>
    )
}
