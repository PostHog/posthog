import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSnack, Spinner } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { isWebAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/country'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import { webAnalyticsDateMapping } from './constants'
import { PagePerformanceFiltersState, pagePerformanceLogic } from './pagePerformanceLogic'
import { PathCleaningToggle } from './PathCleaningToggle'
import { WebAnalyticsDeviceToggle, WebAnalyticsDomainSelector } from './WebAnalyticsFilters'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import { WebConversionGoal } from './WebConversionGoal'
import { WebPropertyFilters } from './WebPropertyFilters'

/**
 * Country and referrer narrow this tab's queries and round-trip through its URL, but neither has a
 * control of its own here the way the domain and device selections do. A shared link that carries
 * one would otherwise filter the numbers with nothing on screen to explain it. Renders nothing when
 * neither is set, which is the usual case.
 */
export interface PagePerformanceFilterController extends PagePerformanceFiltersState {
    rawWebAnalyticsFilters: PagePerformanceFiltersState['webAnalyticsFilters']
    domainFilter: string | null
    deviceTypeFilter: 'Desktop' | 'Mobile' | null
    countryFilter: string | null
    referrerFilter: string | null
    setDates: (dateFrom: string | null, dateTo: string | null) => void
    setCompareFilter: (compareFilter: PagePerformanceFiltersState['compareFilter']) => void
    setConversionGoal: (conversionGoal: PagePerformanceFiltersState['conversionGoal']) => void
    setIsPathCleaningEnabled: (enabled: boolean) => void
    setDomainFilter: (domain: string | null) => void
    setDeviceTypeFilter: (deviceType: 'Desktop' | 'Mobile' | null) => void
    setCountryFilter: (countryCode: string | null) => void
    setReferrerFilter: (referrer: string | null) => void
    setWebAnalyticsFilters: (filters: PagePerformanceFiltersState['webAnalyticsFilters']) => void
}

const ActiveDrillDownFilters = ({
    controller,
}: {
    controller?: PagePerformanceFilterController
}): JSX.Element | null => {
    const webValues = useValues(webAnalyticsLogic)
    const webActions = useActions(webAnalyticsLogic)
    const countryFilter = controller?.countryFilter ?? webValues.countryFilter
    const referrerFilter = controller?.referrerFilter ?? webValues.referrerFilter
    const setCountryFilter = controller?.setCountryFilter ?? webActions.setCountryFilter
    const setReferrerFilter = controller?.setReferrerFilter ?? webActions.setReferrerFilter

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

export const PagePerformanceFilters = ({
    tabs,
    controller,
}: {
    tabs: JSX.Element
    controller?: PagePerformanceFilterController
}): JSX.Element => {
    const webValues = useValues(webAnalyticsLogic)
    const webActions = useActions(webAnalyticsLogic)
    const dateFilter = controller?.dateFilter ?? webValues.dateFilter
    const compareFilter = controller?.compareFilter ?? webValues.compareFilter
    const conversionGoal = controller ? controller.conversionGoal : webValues.conversionGoal
    const isPathCleaningEnabled = controller?.isPathCleaningEnabled ?? webValues.isPathCleaningEnabled
    const setDates = controller?.setDates ?? webActions.setDates
    const setCompareFilter = controller?.setCompareFilter ?? webActions.setCompareFilter
    const setConversionGoal = controller?.setConversionGoal ?? webActions.setConversionGoal
    const setIsPathCleaningEnabled = controller?.setIsPathCleaningEnabled ?? webActions.setIsPathCleaningEnabled
    const { dateTo, dateFrom } = dateFilter
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
                    <WebAnalyticsDomainSelector
                        value={controller?.domainFilter}
                        onChange={controller?.setDomainFilter}
                    />
                    <WebAnalyticsDeviceToggle
                        value={controller?.deviceTypeFilter}
                        onChange={controller?.setDeviceTypeFilter}
                    />
                    <ActiveDrillDownFilters controller={controller} />
                    <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                    <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />
                </>
            }
            right={
                <>
                    <WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />
                    <WebPropertyFilters
                        webAnalyticsFilters={controller?.rawWebAnalyticsFilters}
                        setWebAnalyticsFilters={
                            controller
                                ? (filters) =>
                                      controller.setWebAnalyticsFilters(filters.filter(isWebAnalyticsPropertyFilter))
                                : undefined
                        }
                    />
                </>
            }
        />
    )
}
