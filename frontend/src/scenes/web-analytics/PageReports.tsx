import { useActions, useValues } from 'kea'

import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'

import { pngHoggie } from 'lib/brand/hoggies'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { pageReportsLogic } from './pageReportsLogic'
import { PathCleaningToggle } from './PathCleaningToggle'
import { Tiles } from './WebAnalyticsDashboard'
import { WebAnalyticsCompareFilter, WebAnalyticsDomainSelector } from './WebAnalyticsFilters'

const HedgehogXRay = pngHoggie(xRayPng)

function NoUrlSelectedMessage(): JSX.Element {
    return (
        <div className="border-2 border-dashed border-primary w-full p-8 rounded flex items-center justify-center gap-8">
            <div className="flex-shrink-0">
                <HedgehogXRay title="X-ray hedgehog" className="w-60" />
            </div>
            <div className="flex-1 max-w-140">
                <h2>Select a page to analyze</h2>
                <p className="ml-0">
                    See detailed performance metrics for any page on your site. Just use the search bar above to find
                    and select a page you want to analyze.
                </p>
            </div>
        </div>
    )
}

export function PageReportsFilters({ tabs }: { tabs: JSX.Element }): JSX.Element {
    const { pageUrlOptions, pageUrl, isLoading, dateFilter, pageUrlSearchTerm, featureFlags, isPathCleaningEnabled } =
        useValues(pageReportsLogic)
    const { setPageUrl, setPageUrlSearchTerm, loadPages, setDates, setIsPathCleaningEnabled } =
        useActions(pageReportsLogic)

    const rankedSearchEnabled = !!featureFlags[FEATURE_FLAGS.PAGE_REPORTS_RANKED_URL_SEARCH]

    const emptyStateComponent = rankedSearchEnabled ? (
        <div className="text-muted-alt px-3 py-2 text-xs">
            {pageUrlSearchTerm
                ? `No pages match "${pageUrlSearchTerm}". Press Enter to analyze it as a custom URL.`
                : 'No pageviews in the selected date range. Paste a URL to analyze it anyway.'}
        </div>
    ) : undefined

    return (
        <FilterBar
            top={tabs}
            left={
                <div className="flex flex-row flex-wrap gap-2 items-center w-full min-w-0">
                    <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                    <WebAnalyticsCompareFilter />
                    <LemonInputSelect
                        className="flex-1 min-w-0"
                        allowCustomValues={true}
                        fullWidth={true}
                        placeholder="Click or type to see top pages, or paste a URL"
                        loading={isLoading}
                        size="small"
                        mode="single"
                        value={pageUrl ? [pageUrl] : null}
                        onChange={(val: string[]) => setPageUrl(val.length > 0 ? val[0] : null)}
                        options={pageUrlOptions}
                        onInputChange={(val: string) => setPageUrlSearchTerm(val)}
                        data-attr="page-reports-url-search"
                        onFocus={() => loadPages('')}
                        emptyStateComponent={emptyStateComponent}
                    />
                    <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />
                    <WebAnalyticsDomainSelector />
                </div>
            }
        />
    )
}

export function PageReports(): JSX.Element {
    const { hasPageUrl, tiles } = useValues(pageReportsLogic)

    if (!hasPageUrl) {
        return (
            <div className="space-y-2 mt-2">
                <NoUrlSelectedMessage />
            </div>
        )
    }

    return (
        <div className="space-y-2 mt-2 h-full min-h-0">
            <Tiles tiles={tiles} compact={true} />
        </div>
    )
}
