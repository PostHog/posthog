import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import { webAnalyticsDateMapping } from './constants'
import { pagePerformanceLogic } from './pagePerformanceLogic'
import { PathCleaningToggle } from './PathCleaningToggle'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import { WebConversionGoal } from './WebConversionGoal'

export const PagePerformanceFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        compareFilter,
        conversionGoal,
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setCompareFilter, setConversionGoal, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)
    const { areAnyLoading } = useValues(dataNodeCollectionLogic({ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID }))
    const { reloadAll } = useActions(dataNodeCollectionLogic({ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID }))
    const { overviewLoading, candidatesLoading } = useValues(pagePerformanceLogic)
    const isReloading = areAnyLoading || overviewLoading || candidatesLoading

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={reloadAll}
                        icon={isReloading ? <Spinner textColored /> : <IconRefresh />}
                        disabledReason={isReloading ? 'Loading' : undefined}
                        aria-label="Reload page performance"
                    />
                    <DateFilter
                        dateOptions={webAnalyticsDateMapping}
                        allowTimePrecision
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                    />
                    <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                    <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />
                </>
            }
            right={<WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />}
        />
    )
}
