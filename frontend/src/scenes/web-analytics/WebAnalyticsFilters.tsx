import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconFilter, IconGlobe, IconPhone, IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { IconMonitor } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import MaxTool from 'scenes/max/MaxTool'

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
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <ReloadAll iconOnly />
                    <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />

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
                    <WebAnalyticsCompareFilter />

                    <WebConversionGoal />
                    <TableSortingIndicator />

                    <WebVitalsPercentileToggle />
                    <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />

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
            <WebPropertyFilters />
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
                    footer: showProposedURLForm ? <AddAuthorizedUrlForm /> : <AddSuggetedAuthorizedUrlList />,
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

const AddAuthorizedUrlForm = (): JSX.Element => {
    const { isProposedUrlSubmitting } = useValues(webAnalyticsLogic)
    const { cancelProposingAuthorizedUrl } = useActions(webAnalyticsLogic)

    return (
        <Form
            logic={authorizedUrlListLogic}
            props={{
                actionId: null,
                experimentId: null,
                type: AuthorizedUrlListType.WEB_ANALYTICS,
                allowWildCards: false,
            }}
            formKey="proposedUrl"
            enableFormOnSubmit
        >
            <div className="p-2 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
                <LemonField name="url">
                    <LemonInput size="small" placeholder="https://example.com" autoFocus />
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

const AddSuggetedAuthorizedUrlList = (): JSX.Element => {
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
