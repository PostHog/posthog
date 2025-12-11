import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconGlobe, IconPhone } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect, LemonSwitch, Link, Popover, Tooltip } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { IconLink, IconMonitor, IconWithCount } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import MaxTool from 'scenes/max/MaxTool'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { AvailableFeature, PropertyMathType } from '~/types'

import { PathCleaningToggle } from './PathCleaningToggle'
import { TableSortingIndicator } from './TableSortingIndicator'
import { WebConversionGoal } from './WebConversionGoal'
import {
    WEB_ANALYTICS_PROPERTY_ALLOW_LIST,
    WebPropertyFilters,
    getWebAnalyticsTaxonomicGroupTypes,
} from './WebPropertyFilters'
import { ProductTab } from './common'
import { webAnalyticsLogic } from './webAnalyticsLogic'

const CondensedFilterBar = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
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
                    <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                    <WebAnalyticsCompareFilter />
                </>
            }
            right={
                <>
                    <ShareButton />
                    <WebVitalsPercentileToggle />
                    <FiltersPopover />
                    <WebAnalyticsDeviceToggle />
                    <WebAnalyticsDomainSelector />
                    <TableSortingIndicator />
                </>
            }
        />
    )
}

export const WebAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]) {
        return <CondensedFilterBar tabs={tabs} />
    }

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <ReloadAll iconOnly />
                    <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />

                    <WebAnalyticsDomainSelector />
                    <WebAnalyticsDeviceToggle />
                </>
            }
            right={
                <>
                    <ShareButton />
                    <WebAnalyticsCompareFilter />

                    <WebConversionGoal />
                    <TableSortingIndicator />

                    <WebVitalsPercentileToggle />
                    <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />

                    <WebAnalyticsAIFilters>
                        <WebPropertyFilters />
                    </WebAnalyticsAIFilters>
                </>
            }
        />
    )
}

const WebAnalyticsAIFilters = ({ children }: { children: JSX.Element }): JSX.Element => {
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
        return children
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
            contextDescription={{
                text: 'Current filters',
                icon: <IconFilter />,
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
            {children}
        </MaxTool>
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

const ShareButton = (): JSX.Element => {
    const handleShare = (): void => {
        void copyToClipboard(window.location.href, 'link')
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconLink />}
            tooltip="Share"
            tooltipPlacement="top"
            onClick={handleShare}
            data-attr="web-analytics-share-button"
        />
    )
}

function FiltersPopover(): JSX.Element {
    const [displayFilters, setDisplayFilters] = useState(false)
    const { rawWebAnalyticsFilters, isPathCleaningEnabled, conversionGoal, preAggregatedEnabled, productTab } =
        useValues(webAnalyticsLogic)

    const { setWebAnalyticsFilters, setIsPathCleaningEnabled, setConversionGoal } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { hasAvailableFeature } = useValues(userLogic)

    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const showConversionGoal =
        productTab === ProductTab.ANALYTICS &&
        (!preAggregatedEnabled || featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_PREAGG])

    const taxonomicGroupTypes = getWebAnalyticsTaxonomicGroupTypes(preAggregatedEnabled ?? false)
    const propertyAllowList = preAggregatedEnabled ? WEB_ANALYTICS_PROPERTY_ALLOW_LIST : undefined

    const activeFilterCount = rawWebAnalyticsFilters.length + (conversionGoal ? 1 : 0) + (isPathCleaningEnabled ? 1 : 0)

    const filtersContent = (
        <div className="p-3 w-96 max-w-[90vw]">
            <div className="space-y-4">
                <div>
                    <div className="text-xs font-semibold text-muted uppercase mb-2">Property filters</div>
                    <PropertyFilters
                        disablePopover
                        propertyAllowList={propertyAllowList}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        onChange={(filters) =>
                            setWebAnalyticsFilters(filters.filter(isEventPersonOrSessionPropertyFilter))
                        }
                        propertyFilters={rawWebAnalyticsFilters}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                    />
                </div>

                {showConversionGoal && (
                    <>
                        <LemonDivider />
                        <div>
                            <div className="text-xs font-semibold text-muted uppercase mb-2">Conversion goal</div>
                            <WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />
                        </div>
                    </>
                )}

                {hasAdvancedPaths && (
                    <>
                        <LemonDivider />
                        <div className="flex items-center justify-between">
                            <div>
                                <div className="text-xs font-semibold text-muted uppercase mb-1">Path cleaning</div>
                                <div className="text-xs text-muted">
                                    Standardize URLs by removing parameters.{' '}
                                    <Link to={urls.settings('project-product-analytics', 'path-cleaning')}>
                                        Configure rules
                                    </Link>
                                </div>
                            </div>
                            <LemonSwitch checked={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />
                        </div>
                    </>
                )}
            </div>
        </div>
    )

    const popover = (
        <Popover
            visible={displayFilters}
            onClickOutside={() => setDisplayFilters(false)}
            placement="bottom-end"
            overlay={filtersContent}
        >
            <LemonButton
                icon={
                    <IconWithCount count={activeFilterCount} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
                type="secondary"
                size="small"
                data-attr="web-analytics-unified-filters"
                onClick={() => setDisplayFilters(!displayFilters)}
            >
                Filters
            </LemonButton>
        </Popover>
    )

    return <WebAnalyticsAIFilters>{popover}</WebAnalyticsAIFilters>
}
