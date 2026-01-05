import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { Tiles } from './WebAnalyticsDashboard'
import { WebAnalyticsCompareFilter } from './WebAnalyticsFilters'
import { pageReportsLogic } from './pageReportsLogic'

function NoUrlSelectedMessage(): JSX.Element {
    return (
        <div className="border-2 border-dashed border-primary w-full p-8 rounded flex items-center justify-center gap-8">
            <div className="flex-shrink-0">
                <XRayHog2 alt="X-ray hedgehog" className="w-60" />
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
    const { pagesUrls, pageUrl, isLoading, dateFilter } = useValues(pageReportsLogic)
    const { setPageUrl, setPageUrlSearchTerm, loadPages, setDates } = useActions(pageReportsLogic)

    const options = pagesUrls.map((option: { url: string }) => ({
        key: option.url,
        label: option.url,
    }))

    return (
        <FilterBar
            top={tabs}
            left={
                <div className="flex flex-row gap-2 items-center flex-1 min-w-0 w-full">
                    <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                    <WebAnalyticsCompareFilter />
                    <LemonInputSelect
                        allowCustomValues={true}
                        fullWidth={true}
                        placeholder="Click or type to see top pages, or paste a URL"
                        loading={isLoading}
                        size="small"
                        mode="single"
                        value={pageUrl ? [pageUrl] : null}
                        onChange={(val: string[]) => setPageUrl(val.length > 0 ? val[0] : null)}
                        options={options}
                        onInputChange={(val: string) => setPageUrlSearchTerm(val)}
                        data-attr="page-reports-url-search"
                        onFocus={() => loadPages('')}
                    />
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
