import { useActions, useValues } from 'kea'

import { IconGlobe, IconPhone } from '@posthog/icons'
import { LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { IconMonitor } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { PropertyMathType } from '~/types'

import { PathCleaningToggle } from './PathCleaningToggle'
import { TableSortingIndicator } from './TableSortingIndicator'
import { WebAnalyticsLiveUserCount } from './WebAnalyticsLiveUserCount'
import { WebConversionGoal } from './WebConversionGoal'
import { WebPropertyFilters } from './WebPropertyFilters'
import { ProductTab } from './common'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export const WebAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        preAggregatedEnabled,
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <ReloadAll iconOnly />

                    <WebAnalyticsDomainSelector />
                    <WebAnalyticsDeviceToggle />

                    <div className="hidden ml-2 md:flex items-center gap-2">
                        <span className="text-muted-alt">|</span>
                        <WebAnalyticsLiveUserCount />
                    </div>
                </>
            }
            right={
                <>
                    <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                    <WebAnalyticsCompareFilter />

                    {(!preAggregatedEnabled || featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_PREAGG]) && (
                        <WebConversionGoal />
                    )}
                    <TableSortingIndicator />

                    <WebVitalsPercentileToggle />
                    <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />

                    <WebPropertyFilters />
                </>
            }
        />
    )
}

const DomainSettingsLink = (): JSX.Element => (
    <Link to={urls.settings('environment', 'web-analytics-authorized-urls')}>settings</Link>
)

const WebAnalyticsDomainSelector = (): JSX.Element => {
    const { domainFilter, hasHostFilter, authorizedDomains } = useValues(webAnalyticsLogic)
    const { setDomainFilter } = useActions(webAnalyticsLogic)

    return (
        <LemonSelect
            className="grow md:grow-0"
            size="small"
            value={hasHostFilter ? 'host' : (domainFilter ?? 'all')}
            icon={<IconGlobe />}
            onChange={(value) => setDomainFilter(value)}
            disabledReason={
                authorizedDomains.length === 0 ? (
                    <span>
                        No authorized domains, authorize them on <DomainSettingsLink />
                    </span>
                ) : undefined
            }
            options={[
                {
                    options: [
                        {
                            label: 'All domains',
                            value: 'all',
                        },
                        ...(hasHostFilter
                            ? [
                                  {
                                      label: 'All domains (host filter active)',
                                      value: 'host',
                                  },
                              ]
                            : []),
                        ...authorizedDomains.map((domain) => ({ label: domain, value: domain })),
                    ],
                    footer: (
                        <span className="text-xs px-2">
                            Have more domains? Go to <DomainSettingsLink />
                        </span>
                    ),
                },
            ]}
        />
    )
}

const WebAnalyticsDeviceToggle = (): JSX.Element => {
    const { deviceTypeFilter } = useValues(webAnalyticsLogic)
    const { setDeviceTypeFilter } = useActions(webAnalyticsLogic)

    return (
        <LemonSegmentedSelect
            size="small"
            value={deviceTypeFilter ?? undefined}
            onChange={(value) => setDeviceTypeFilter(value !== deviceTypeFilter ? value : null)}
            options={[
                {
                    value: 'Desktop',
                    label: <IconMonitor className="mx-1" />,
                    tooltip: 'Desktop devices include laptops and desktops.',
                },
                {
                    value: 'Mobile',
                    label: <IconPhone className="mx-1" />,
                    tooltip: 'Mobile devices include smartphones and tablets.',
                },
            ]}
        />
    )
}

const WebVitalsPercentileToggle = (): JSX.Element | null => {
    const { webVitalsPercentile, productTab } = useValues(webAnalyticsLogic)
    const { setWebVitalsPercentile } = useActions(webAnalyticsLogic)

    if (productTab !== ProductTab.WEB_VITALS) {
        return null
    }

    return (
        <LemonSegmentedSelect
            value={webVitalsPercentile}
            onChange={setWebVitalsPercentile}
            options={[
                { value: PropertyMathType.P75, label: 'P75' },
                {
                    value: PropertyMathType.P90,
                    label: (
                        <Tooltip title="P90 is recommended by the standard as a good baseline" delayMs={0}>
                            P90
                        </Tooltip>
                    ),
                },
                { value: PropertyMathType.P99, label: 'P99' },
            ]}
        />
    )
}

export const WebAnalyticsCompareFilter = (): JSX.Element | null => {
    const { compareFilter, productTab } = useValues(webAnalyticsLogic)
    const { setCompareFilter } = useActions(webAnalyticsLogic)

    if (![ProductTab.ANALYTICS, ProductTab.PAGE_REPORTS].includes(productTab)) {
        return null
    }

    return <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
}
