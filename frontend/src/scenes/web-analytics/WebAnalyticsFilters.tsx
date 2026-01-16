import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { IconFilter, IconGlobe, IconPhone, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonSelect, Popover, Tooltip } from '@posthog/lemon-ui'

import { baseModifier } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { LiveUserCount } from 'lib/components/LiveUserCount'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { IconLink, IconMonitor, IconWithCount } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import MaxTool from 'scenes/max/MaxTool'
import { Scene } from 'scenes/sceneTypes'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { PropertyMathType } from '~/types'

import { PathCleaningToggle } from './PathCleaningToggle'
import { TableSortingIndicator } from './TableSortingIndicator'
import { FilterPresetsDropdown } from './WebAnalyticsFilterPresets'
import { WebAnalyticsFiltersV2MigrationBanner } from './WebAnalyticsFiltersV2MigrationBanner'
import { WebConversionGoal } from './WebConversionGoal'
import {
    WEB_ANALYTICS_PROPERTY_ALLOW_LIST,
    WebPropertyFilters,
    getWebAnalyticsTaxonomicGroupTypes,
} from './WebPropertyFilters'
import { ProductTab } from './common'
import { webAnalyticsFilterPresetsLogic } from './webAnalyticsFilterPresetsLogic'
import { webAnalyticsLogic } from './webAnalyticsLogic'

const CondensedWebAnalyticsFilterBar = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <WebAnalyticsFiltersV2MigrationBanner />
            <IncompatibleFiltersWarning />
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
                        {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] && <FilterPresetsDropdown />}
                        <FiltersPopover />
                        <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />
                        <WebAnalyticsDomainSelector />
                        <TableSortingIndicator />
                    </>
                }
            />
        </>
    )
}

export const WebAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] || featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]) {
        return <CondensedWebAnalyticsFilterBar tabs={tabs} />
    }

    return (
        <>
            <IncompatibleFiltersWarning />
            <FilterBar
                top={tabs}
                left={
                    <>
                        <ReloadAll iconOnly />
                        <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />

                        <WebAnalyticsDomainSelector />
                        <WebAnalyticsDeviceToggle />
                        <LiveUserCount
                            docLink="https://posthog.com/docs/web-analytics/faq#i-am-online-but-the-online-user-count-is-not-reflecting-my-user"
                            dataAttr="web-analytics-live-user-count"
                        />
                    </>
                }
                right={
                    <>
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
        </>
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

const WebAnalyticsDomainSelector = (): JSX.Element => {
    const { validatedDomainFilter, hasHostFilter, authorizedDomains, showProposedURLForm } =
        useValues(webAnalyticsLogic)
    const { setDomainFilter } = useActions(webAnalyticsLogic)

    return (
        <LemonSelect
            className="grow md:grow-0"
            size="small"
            value={hasHostFilter ? 'host' : (validatedDomainFilter ?? 'all')}
            icon={<IconGlobe />}
            onChange={(value) => setDomainFilter(value)}
            menu={{ closeParentPopoverOnClickInside: !showProposedURLForm }}
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
                    footer: showProposedURLForm ? <AddAuthorizedUrlForm /> : <AddSuggestedAuthorizedUrlList />,
                },
            ]}
        />
    )
}

const WebAnalyticsDeviceToggle = (): JSX.Element => {
    const { deviceTypeFilter } = useValues(webAnalyticsLogic)
    const { setDeviceTypeFilter } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Device toggle shortcuts (Web Analytics-specific)
    useAppShortcut({
        name: 'WebAnalyticsDesktop',
        keybind: [[...baseModifier, 'p']],
        intent: 'Filter desktop devices',
        interaction: 'function',
        callback: () => setDeviceTypeFilter(deviceTypeFilter === 'Desktop' ? null : 'Desktop'),
        scope: Scene.WebAnalytics,
    })
    useAppShortcut({
        name: 'WebAnalyticsMobile',
        keybind: [[...baseModifier, 'm']],
        intent: 'Filter mobile devices',
        interaction: 'function',
        callback: () => setDeviceTypeFilter(deviceTypeFilter === 'Mobile' ? null : 'Mobile'),
        scope: Scene.WebAnalytics,
    })

    if (featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] || featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]) {
        return (
            <LemonSelect
                size="small"
                value={deviceTypeFilter ?? undefined}
                allowClear={true}
                onChange={(value) => setDeviceTypeFilter(value !== deviceTypeFilter ? value : null)}
                options={[
                    {
                        value: 'Desktop',
                        label: (
                            <div>
                                <IconMonitor className="mx-1" /> Desktop
                            </div>
                        ),
                        tooltip: 'Desktop devices include laptops and desktops.',
                    },
                    {
                        value: 'Mobile',
                        label: (
                            <div>
                                <IconPhone className="mx-1" /> Mobile
                            </div>
                        ),
                        tooltip: 'Mobile devices include smartphones and tablets.',
                    },
                ]}
            />
        )
    }

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
    const { activePreset } = useValues(webAnalyticsFilterPresetsLogic)

    const handleShare = (): void => {
        const url = new URL(window.location.href)

        if (activePreset) {
            url.search = ''
            url.searchParams.set('presetId', activePreset.short_id)
        }

        void copyToClipboard(url.toString(), 'link')
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
    const { rawWebAnalyticsFilters, conversionGoal, preAggregatedEnabled, productTab } = useValues(webAnalyticsLogic)

    const { setWebAnalyticsFilters, setConversionGoal } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Toggle filters shortcut
    useAppShortcut({
        name: 'WebAnalyticsFilters',
        keybind: [[...baseModifier, 'f']],
        intent: 'Toggle filters',
        interaction: 'function',
        callback: () => setDisplayFilters((prev) => !prev),
        scope: Scene.WebAnalytics,
    })

    const showConversionGoal =
        productTab === ProductTab.ANALYTICS &&
        (!preAggregatedEnabled || featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_PREAGG])

    const taxonomicGroupTypes = getWebAnalyticsTaxonomicGroupTypes(preAggregatedEnabled ?? false)
    const propertyAllowList = preAggregatedEnabled ? WEB_ANALYTICS_PROPERTY_ALLOW_LIST : undefined

    const activeFilterCount = rawWebAnalyticsFilters.length + (conversionGoal ? 1 : 0)

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

                <LemonDivider />
                <div className="text-xs font-semibold text-muted uppercase mb-2">Device filters</div>
                <WebAnalyticsDeviceToggle />

                {showConversionGoal && (
                    <>
                        <LemonDivider />
                        <div>
                            <div className="text-xs font-semibold text-muted uppercase mb-2">Conversion goal</div>
                            <WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />
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

const AddAuthorizedUrlForm = (): JSX.Element => {
    const { isProposedUrlSubmitting } = useValues(webAnalyticsLogic)
    const { cancelProposingAuthorizedUrl } = useActions(webAnalyticsLogic)

    return (
        <Form
            logic={authorizedUrlListLogic}
            props={{
                actionId: null,
                experimentId: null,
                productTourId: null,
                type: AuthorizedUrlListType.WEB_ANALYTICS,
                allowWildCards: false,
            }}
            formKey="proposedUrl"
            enableFormOnSubmit
        >
            <div className="p-2 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
                <LemonField name="url">
                    <LemonInput
                        size="small"
                        placeholder="https://example.com"
                        autoFocus
                        data-attr="web-authorized-url-input"
                    />
                </LemonField>
                <div className="flex gap-2 justify-end">
                    <LemonButton size="small" type="secondary" onClick={cancelProposingAuthorizedUrl}>
                        Cancel
                    </LemonButton>
                    <LemonButton size="small" type="primary" htmlType="submit" loading={isProposedUrlSubmitting}>
                        Add
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}

const AddSuggestedAuthorizedUrlList = (): JSX.Element => {
    const { urlSuggestions } = useValues(webAnalyticsLogic)
    const { addAuthorizedUrl, newAuthorizedUrl } = useActions(webAnalyticsLogic)

    return (
        <div className="flex flex-col gap-1 p-1" onClick={(e) => e.stopPropagation()}>
            {urlSuggestions.length > 0 && (
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted px-1">Suggestions</span>
                    {urlSuggestions.slice(0, 3).map((suggestion) => (
                        <div key={suggestion.url} className="flex items-center justify-between gap-2 px-1">
                            <span className="text-xs truncate flex-1" title={suggestion.url}>
                                {suggestion.url}
                            </span>
                            <LemonButton size="xsmall" type="primary" onClick={() => addAuthorizedUrl(suggestion.url)}>
                                Add
                            </LemonButton>
                        </div>
                    ))}
                </div>
            )}
            <LemonButton size="small" icon={<IconPlus />} onClick={newAuthorizedUrl} fullWidth>
                Add authorized URL
            </LemonButton>
        </div>
    )
}

const IncompatibleFiltersWarning = (): JSX.Element | null => {
    const { hasIncompatibleFilters, incompatibleFilters, preAggregatedEnabled } = useValues(webAnalyticsLogic)
    const { removeIncompatibleFilters } = useActions(webAnalyticsLogic)

    if (!preAggregatedEnabled || !hasIncompatibleFilters) {
        return null
    }

    const filterNames = incompatibleFilters.map((filter) => filter.key).join(', ')

    return (
        <LemonBanner type="warning" className="mb-2">
            <div className="flex items-center justify-between w-full">
                <div>
                    <div className="font-semibold">Some filters are slowing down your queries</div>
                    <div className="text-sm mt-0.5">
                        The following filters are not supported by the new query engine and are causing your queries to
                        slow down: <strong>{filterNames}</strong>
                    </div>
                </div>
                <LemonButton type="primary" size="small" onClick={removeIncompatibleFilters}>
                    Remove unsupported filters
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
