import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSnack, Spinner } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/country'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { SearchAndAiFiltersPopover } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiFiltersPopover'

import { WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import { webAnalyticsDateMapping } from './constants'
import { pagePerformanceLogic } from './pagePerformanceLogic'
import { PathCleaningToggle } from './PathCleaningToggle'
import { WebAnalyticsDomainSelector } from './WebAnalyticsFilters'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import { WebConversionGoal } from './WebConversionGoal'

/**
 * Country and referrer narrow this tab's queries and round-trip through its URL, but neither has a
 * control of its own here the way the domain selection does. A shared link that carries
 * one would otherwise filter the numbers with nothing on screen to explain it. Renders nothing when
 * neither is set, which is the usual case.
 */
const ActiveDrillDownFilters = (): JSX.Element | null => {
    const { countryFilter, referrerFilter } = useValues(webAnalyticsLogic)
    const { setCountryFilter, setReferrerFilter } = useActions(webAnalyticsLogic)

    if (!countryFilter && !referrerFilter) {
        return null
    }

    return (
        <>
            {countryFilter && (
                <LemonSnack onClose={() => setCountryFilter(null)}>
                    Country: {countryCodeToFlag(countryFilter)}{' '}
                    {COUNTRY_CODE_TO_LONG_NAME[countryFilter] ?? countryFilter}
                </LemonSnack>
            )}
            {referrerFilter && (
                <LemonSnack onClose={() => setReferrerFilter(null)}>Referrer: {referrerFilter}</LemonSnack>
            )}
        </>
    )
}

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
                        aria-label="Reload Search & AI"
                    />
                    <DateFilter
                        dateOptions={webAnalyticsDateMapping}
                        allowTimePrecision
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                    />
                    <WebAnalyticsDomainSelector />
                    <ActiveDrillDownFilters />
                    <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                    <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />
                    <WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />
                    <SearchAndAiFiltersPopover />
                </>
            }
        />
    )
}
