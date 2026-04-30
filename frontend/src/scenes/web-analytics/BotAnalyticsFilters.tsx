import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

import { BotPropertyFilters } from './BotPropertyFilters'
import { webAnalyticsDateMapping } from './constants'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export const BotAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
    } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <ReloadAll iconOnly />
                    <DateFilter
                        dateOptions={webAnalyticsDateMapping}
                        allowTimePrecision
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                    />
                    <BotPropertyFilters />
                </>
            }
        />
    )
}
