import { IconFilter, IconGear, IconGlobe } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IconBranch, IconMonitor, IconPhone } from 'lib/lemon-ui/icons/icons'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { AvailableFeature, PropertyMathType } from '~/types'

import { TableSortingIndicator } from './TableSortingIndicator'
import { WebAnalyticsLiveUserCount } from './WebAnalyticsLiveUserCount'
import { ProductTab, webAnalyticsLogic } from './webAnalyticsLogic'
import { WebConversionGoal } from './WebConversionGoal'
import { WebPropertyFilters } from './WebPropertyFilters'

export const WebAnalyticsFilters = (): JSX.Element => {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="flex flex-col md:flex-row md:justify-between gap-2">
            <div className="flex items-start shrink-0">
                <div className="flex flex-1 flex-row gap-2 items-center">
                    <div className="flex flex-row gap-1 items-center flex-1 md:flex-none">
                        <ReloadAll iconOnly />

                        <WebAnalyticsDomainSelector />
                        <WebAnalyticsDeviceToggle />
                    </div>

                    <div className="hidden md:flex items-center gap-2">
                        <span className="text-muted-alt">|</span>
                        <WebAnalyticsLiveUserCount />
                    </div>

                    <LemonButton
                        type="secondary"
                        size="small"
                        className="sm:hidden"
                        onClick={() => setExpanded((expanded) => !expanded)}
                        icon={<IconFilter />}
                    />
                </div>
            </div>

            {/* On more than mobile, just display Foldable Fields, on smaller delegate displaying it to the expanded state */}
            <div className="hidden sm:flex gap-2">
                <FoldableFilters />
            </div>

            <div
                className={clsx(
                    'flex sm:hidden flex-col gap-2 overflow-hidden transition-all duration-200',
                    expanded ? 'max-h-[500px]' : 'max-h-0'
                )}
            >
                <FoldableFilters />
            </div>
        </div>
    )
}

const FoldableFilters = (): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        preAggregatedEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)
    return (
        <div className="flex flex-row md:flex-row-reverse flex-wrap gap-2 md:[&>*]:grow-0 [&>*]:grow w-full">
            <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            <WebAnalyticsCompareFilter />

            {!preAggregatedEnabled && <WebConversionGoal />}
            <TableSortingIndicator />

            <WebVitalsPercentileToggle />
            <PathCleaningToggle />

            <WebPropertyFilters />
        </div>
    )
}

const PathCleaningToggle = (): JSX.Element | null => {
    const { isPathCleaningEnabled } = useValues(webAnalyticsLogic)
    const { setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)

    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    if (!hasAdvancedPaths) {
        return null
    }

    return (
        <Tooltip
            title={
                <div className="p-2">
                    <p className="mb-2">
                        Path cleaning helps standardize URLs by removing unnecessary parameters and fragments.
                    </p>
                    <div className="mb-2">
                        <Link to="https://posthog.com/docs/product-analytics/paths#path-cleaning-rules">
                            Learn more about path cleaning rules
                        </Link>
                    </div>
                    <LemonButton
                        icon={<IconGear />}
                        type="primary"
                        size="small"
                        to={urls.settings('project-product-analytics', 'path-cleaning')}
                        targetBlank
                        className="w-full"
                    >
                        Edit path cleaning settings
                    </LemonButton>
                </div>
            }
            placement="top"
            interactive={true}
        >
            <LemonButton
                icon={<IconBranch />}
                onClick={() => setIsPathCleaningEnabled(!isPathCleaningEnabled)}
                type="secondary"
                size="small"
            >
                Path cleaning: <LemonSwitch checked={isPathCleaningEnabled} className="ml-1" />
            </LemonButton>
        </Tooltip>
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
