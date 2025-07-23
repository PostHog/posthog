import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { webAnalyticsLogic } from '../../../../../webAnalyticsLogic'
import { WebAnalyticsCompareFilter } from 'scenes/web-analytics/WebAnalyticsFilters'

export const MarketingAnalyticsFilters = (): JSX.Element => {
    const {
        dateFilter: { dateFrom, dateTo },
    } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)

    return (
        <div className="flex flex-col md:flex-row md:justify-between gap-2">
            <ReloadAll />
            <div className="flex flex-row gap-2 items-center">
                <WebAnalyticsCompareFilter />
                <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            </div>
        </div>
    )
}
