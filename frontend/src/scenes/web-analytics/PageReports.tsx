import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { pageReportsLogic } from './pageReportsLogic'
import { Tiles } from './WebAnalyticsDashboard'

export function PageReportsFilters(): JSX.Element {
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
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <div className="flex-1">
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
                        data-attr="page-url-search"
                        onFocus={() => loadPages('')}
                        className="max-w-full"
                    />
                </div>
                <Tooltip title="Strip query parameters from URLs (e.g. '?utm_source=...'). This will match the base URL regardless of query parameters.">
                    <div className="inline-block">
                        <LemonSwitch
                            checked={stripQueryParams}
                            onChange={toggleStripQueryParams}
                            label="Strip query params"
                            size="small"
                            bordered
                        />
                    </div>
                </Tooltip>
                <div>
                    <DateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={(fromDate, toDate) => setDates(fromDate, toDate)}
                    />
                </div>
            </div>
        </div>
    )
}

export function PageReports(): JSX.Element {
    const { hasPageUrl, tiles } = useValues(pageReportsLogic)

    if (!hasPageUrl) {
        return (
            <div className="space-y-2 mt-2">
                <ProductIntroduction
                    productName="PAGE REPORTS"
                    thingName="page report"
                    description="Page Reports provide in-depth analytics for individual pages on your website. Use the search bar above to select a specific page and see detailed metrics."
                    isEmpty={true}
                    customHog={() => <XRayHog2 alt="X-ray hedgehog" className="w-60" />}
                />
            </div>
        )
    }

    return (
        <div className="space-y-2 mt-2">
            <Tiles tiles={tiles} />
        </div>
    )
}
