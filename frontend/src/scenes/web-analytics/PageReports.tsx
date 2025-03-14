import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { QuerySchema } from '~/queries/schema/schema-general'

import { pageReportsLogic } from './pageReportsLogic'
import { WebQuery } from './tiles/WebAnalyticsTile'
import { LearnMorePopover } from './WebAnalyticsDashboard'
import { TileId, webAnalyticsLogic } from './webAnalyticsLogic'

export function PageReportsFilters(): JSX.Element {
    const { pagesUrls, pageUrl, isLoading, stripQueryParams, dateFilter } = useValues(pageReportsLogic)
    const { setPageUrl, setPageUrlSearchTerm, toggleStripQueryParams, loadPages, setDates } =
        useActions(pageReportsLogic)

    const options = pagesUrls.map((option) => ({
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

const SimpleTile = ({
    title,
    description,
    query,
    tileId,
}: {
    title: string
    description: string
    query: QuerySchema | undefined
    tileId: TileId
}): JSX.Element => {
    const { createInsightProps } = useValues(pageReportsLogic)

    // If query is undefined, show a placeholder
    if (!query) {
        return (
            <div className="border rounded p-4 bg-bg-light">
                <div className="flex justify-between items-center mb-1">
                    <div className="flex items-center">
                        <h3 className="text-base font-semibold m-0">{title}</h3>
                        <LearnMorePopover title={title} description={description} />
                    </div>
                </div>
                <div className="text-muted text-center py-8">Select url to view data</div>
            </div>
        )
    }

    return (
        <div>
            <div className="flex justify-between items-center mb-1">
                <div className="flex items-center">
                    <h3 className="text-base font-semibold m-0">{title}</h3>
                    <LearnMorePopover title={title} description={description} />
                </div>
            </div>
            <div>
                <WebQuery
                    query={query}
                    showIntervalSelect={false}
                    tileId={tileId}
                    insightProps={createInsightProps(tileId)}
                />
            </div>
        </div>
    )
}

export const PageReports = (): JSX.Element => {
    const { dateFilter, compareFilter } = useValues(webAnalyticsLogic)
    const { hasPageUrl, queries, createInsightProps, combinedMetricsQuery, pageUrl } = useValues(pageReportsLogic)

    // Always prepare the combinedMetricsQuery even if we don't use it
    // This ensures the same hooks are called regardless of hasPageUrl
    const combinedMetrics = combinedMetricsQuery(dateFilter, compareFilter)

    const Section = ({ title, children }: { title: string; children: React.ReactNode }): JSX.Element => {
        return (
            <>
                <div className="flex items-center justify-between mb-2">
                    <h2 className="text-xl font-semibold">{title}</h2>
                </div>
                {children}
                <LemonDivider className="my-4" />
            </>
        )
    }

    // If we don't have a page URL, show the introduction
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

    // Otherwise, show the full report
    return (
        <div className="space-y-2 mt-2">
            {/* Trends Section */}
            <Section title="Trends over time">
                <div className="w-full min-h-[350px]">
                    <WebQuery
                        query={combinedMetrics}
                        showIntervalSelect={true}
                        tileId={TileId.PAGE_REPORTS_COMBINED_METRICS_CHART}
                        insightProps={createInsightProps(TileId.PAGE_REPORTS_COMBINED_METRICS_CHART, 'combined')}
                        key={`combined-metrics-${pageUrl}`}
                    />
                </div>
            </Section>

            {/* Page Paths Analysis Section */}
            <Section title="Page Paths Analysis">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    <SimpleTile
                        title="Entry Paths"
                        description="How users arrive at this page"
                        query={queries.entryPathsQuery}
                        tileId={TileId.PAGE_REPORTS_ENTRY_PATHS}
                    />

                    <SimpleTile
                        title="Exit Paths"
                        description="Where users go after viewing this page"
                        query={queries.exitPathsQuery}
                        tileId={TileId.PAGE_REPORTS_EXIT_PATHS}
                    />

                    <SimpleTile
                        title="Outbound Clicks"
                        description="External links users click on this page"
                        query={queries.outboundClicksQuery}
                        tileId={TileId.PAGE_REPORTS_OUTBOUND_CLICKS}
                    />
                </div>
            </Section>

            {/* Traffic Sources Section */}
            <Section title="Traffic Sources">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    <SimpleTile
                        title="Channels"
                        description="Marketing channels bringing users to this page"
                        query={queries.channelsQuery}
                        tileId={TileId.PAGE_REPORTS_CHANNELS}
                    />

                    <SimpleTile
                        title="Referrers"
                        description="Websites referring traffic to this page"
                        query={queries.referrersQuery}
                        tileId={TileId.PAGE_REPORTS_REFERRERS}
                    />
                </div>
            </Section>

            {/* Device Information Section */}
            <Section title="Device Information">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    <SimpleTile
                        title="Device Types"
                        description="Types of devices used to access this page"
                        query={queries.deviceTypeQuery}
                        tileId={TileId.PAGE_REPORTS_DEVICE_TYPES}
                    />

                    <SimpleTile
                        title="Browsers"
                        description="Browsers used to access this page"
                        query={queries.browserQuery}
                        tileId={TileId.PAGE_REPORTS_BROWSERS}
                    />

                    <SimpleTile
                        title="Operating Systems"
                        description="Operating systems used to access this page"
                        query={queries.osQuery}
                        tileId={TileId.PAGE_REPORTS_OPERATING_SYSTEMS}
                    />
                </div>
            </Section>

            {/* Geography Section */}
            <Section title="Geography">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    <SimpleTile
                        title="Countries"
                        description="Countries where users access this page from"
                        query={queries.countriesQuery}
                        tileId={TileId.PAGE_REPORTS_COUNTRIES}
                    />

                    <SimpleTile
                        title="Regions"
                        description="Regions where users access this page from"
                        query={queries.regionsQuery}
                        tileId={TileId.PAGE_REPORTS_REGIONS}
                    />

                    <SimpleTile
                        title="Cities"
                        description="Cities where users access this page from"
                        query={queries.citiesQuery}
                        tileId={TileId.PAGE_REPORTS_CITIES}
                    />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                    <SimpleTile
                        title="Timezones"
                        description="Timezones where users access this page from"
                        query={queries.timezonesQuery}
                        tileId={TileId.PAGE_REPORTS_TIMEZONES}
                    />

                    <SimpleTile
                        title="Languages"
                        description="Languages of users accessing this page"
                        query={queries.languagesQuery}
                        tileId={TileId.PAGE_REPORTS_LANGUAGES}
                    />
                </div>
            </Section>
        </div>
    )
}
