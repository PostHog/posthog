import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'

export const MarketingAnalyticsFilters = (): JSX.Element => {
    const { compareFilter, dateFilter } = useValues(marketingAnalyticsLogic)
    const { setCompareFilter, setDates } = useActions(marketingAnalyticsLogic)

    return (
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
    )
}
