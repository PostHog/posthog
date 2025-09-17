import { useActions, useValues } from 'kea'

import { IconAsterisk, IconGlobe } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
    const { pagesUrls, pageUrl, isLoading, stripQueryParams, dateFilter } = useValues(pageReportsLogic)
    const { setPageUrl, setPageUrlSearchTerm, toggleStripQueryParams, loadPages, setDates } =
        useActions(pageReportsLogic)

    const options = pagesUrls.map((option: { url: string; count: number }) => ({
        key: option.url,
        label: option.url,
        labelComponent: (
            <div className="flex justify-between items-center w-full">
                <span className="truncate">{option.url}</span>
                <span className="text-muted ml-2">{option.count.toLocaleString()}</span>
            </div>
        ),
    }))

    return (
        <FilterBar
            top={tabs}
            left={
                <div className="flex-1">
                    <div className="relative">
                        <IconGlobe className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
                        <LemonInputSelect
                            allowCustomValues={false}
                            placeholder="Click or type to see top pages"
                            loading={isLoading}
                            size="small"
                            mode="single"
                            value={pageUrl ? [pageUrl] : null}
                            onChange={(val: string[]) => setPageUrl(val.length > 0 ? val[0] : null)}
                            options={options}
                            onInputChange={(val: string) => setPageUrlSearchTerm(val)}
                            data-attr="page-reports-url-search"
                            onFocus={() => loadPages('')}
                            className="max-w-full pl-8"
                        />
                    </div>
                </div>
            }
            right={
                <>
                    <Tooltip title="Strip query parameters from URLs (e.g. '?utm_source=...'). This will match the base URL regardless of query parameters.">
                        <LemonButton
                            icon={<IconAsterisk />}
                            onClick={toggleStripQueryParams}
                            type="secondary"
                            size="small"
                        >
                            Strip query parameters: <LemonSwitch checked={stripQueryParams} className="ml-1" />
                        </LemonButton>
                    </Tooltip>
                    <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                    <WebAnalyticsCompareFilter />
                </>
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
