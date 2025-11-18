import { useActions, useValues } from 'kea'

import { IconExternal, IconGear, IconGlobe, IconPhone } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { IconBranch, IconMonitor } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { AvailableFeature, PropertyMathType } from '~/types'

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
    } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)
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
                    <PathCleaningToggle />

                    <WebAnalyticsAIFilters />
                </>
            }
        />
    )
}

const WebAnalyticsAIFilters = (): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        rawWebAnalyticsFilters,
        isPathCleaningEnabled,
        compareFilter,
    } = useValues(webAnalyticsLogic)
    const { setDates, setWebAnalyticsFilters, setIsPathCleaningEnabled, setCompareFilter } =
        useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_POSTHOG_AI]) {
        return <WebPropertyFilters />
    }

    return (
        <MaxTool
            identifier="filter_web_analytics"
            context={{
                current_filters: {
                    date_from: dateFrom,
                    date_to: dateTo,
                    properties: rawWebAnalyticsFilters,
                    doPathCleaning: isPathCleaningEnabled,
                    compareFilter: compareFilter,
                },
            }}
            callback={(toolOutput: Record<string, any>) => {
                if (toolOutput.properties !== undefined) {
                    setWebAnalyticsFilters(toolOutput.properties)
                }
                if (toolOutput.date_from !== undefined && toolOutput.date_to !== undefined) {
                    setDates(toolOutput.date_from, toolOutput.date_to)
                }
                if (toolOutput.doPathCleaning !== undefined) {
                    setIsPathCleaningEnabled(toolOutput.doPathCleaning)
                }
                if (toolOutput.compareFilter !== undefined) {
                    setCompareFilter(toolOutput.compareFilter)
                }
            }}
            initialMaxPrompt="Filter web analytics data for "
            suggestions={[
                'Show mobile traffic from last 30 days for the US',
                'Filter only sessions greater than 2 minutes coming from organic search',
                "Don't include direct traffic and show data for the last 7 days",
            ]}
        >
            <WebPropertyFilters />
        </MaxTool>
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

const WebAnalyticsDomainSelector = (): JSX.Element => {
    const { domainFilter, hasHostFilter, authorizedDomains } = useValues(webAnalyticsLogic)
    const { setDomainFilter } = useActions(webAnalyticsLogic)

    if (hasHostFilter) {
        return (
            <LemonButton
                className="grow md:grow-0"
                size="small"
                icon={<IconGlobe />}
                type="secondary"
                disabledReason="Host filter is active from property filters"
            >
                All domains (host filter active)
            </LemonButton>
        )
    }

    const isAllDomainsSelected = !domainFilter || domainFilter.length === 0
    const selectedCount = domainFilter?.length ?? 0

    const handleToggleDomain = (domain: string): void => {
        if (!domainFilter || domainFilter.length === 0) {
            // If "All domains" is selected, selecting a domain switches to that domain only
            setDomainFilter([domain])
        } else if (domainFilter.includes(domain)) {
            // If domain is already selected, remove it
            const newFilter = domainFilter.filter((d) => d !== domain)
            setDomainFilter(newFilter.length > 0 ? newFilter : null)
        } else {
            // Add domain to selection
            setDomainFilter([...domainFilter, domain])
        }
    }

    const handleToggleAllDomains = (): void => {
        setDomainFilter(null)
    }

    const isDisabled = authorizedDomains.length === 0

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div style={{ minWidth: 200 }}>
                    <div className="space-y-px p-1">
                        {/* "All domains" option */}
                        <LemonButton
                            fullWidth
                            type="tertiary"
                            size="small"
                            onClick={handleToggleAllDomains}
                            icon={<LemonCheckbox checked={isAllDomainsSelected} className="pointer-events-none" />}
                        >
                            All domains
                        </LemonButton>

                        {/* Individual domain options */}
                        {authorizedDomains.map((domain) => {
                            const isSelected = domainFilter?.includes(domain) ?? false
                            return (
                                <LemonButton
                                    key={domain}
                                    fullWidth
                                    type="tertiary"
                                    size="small"
                                    onClick={() => handleToggleDomain(domain)}
                                    icon={<LemonCheckbox checked={isSelected} className="pointer-events-none" />}
                                    sideAction={{
                                        icon: <IconExternal />,
                                        tooltip: 'Open domain',
                                        onClick: (e) => {
                                            e.stopPropagation()
                                            window.open(domain, '_blank', 'noopener,noreferrer')
                                        },
                                    }}
                                >
                                    {domain}
                                </LemonButton>
                            )
                        })}
                    </div>

                    {/* Footer with settings link */}
                    <div className="text-xs px-2 py-1.5 text-muted border-t">
                        Have more domains? Go to{' '}
                        <Link to={urls.settings('environment', 'web-analytics-authorized-urls')}>settings</Link>
                    </div>
                </div>
            }
        >
            <LemonButton
                className="grow md:grow-0"
                size="small"
                icon={<IconGlobe />}
                type="secondary"
                disabled={isDisabled}
                disabledReason={isDisabled ? 'No authorized domains. Configure them in settings.' : undefined}
                data-attr="web-analytics-domain-selector"
            >
                {isAllDomainsSelected ? 'All domains' : `${selectedCount} selected`}
            </LemonButton>
        </LemonDropdown>
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
