import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { pageReportsLogic } from './pageReportsLogic'
import { WebQuery } from './tiles/WebAnalyticsTile'
import { LearnMorePopover } from './WebAnalyticsDashboard'
import { TileId, webAnalyticsLogic } from './webAnalyticsLogic'

function PageUrlSearchHeader(): JSX.Element {
    const values = useValues(pageReportsLogic)
    const actions = useActions(pageReportsLogic)
    const { dateFilter } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)

    // Convert PageURL[] to LemonInputSelectOption[]
    const options = values.pageUrlSearchOptionsWithCount.map((option) => ({
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
        <div className="flex flex-col gap-2 mb-4">
            <div className="flex items-center gap-2">
                <div className="flex-1">
                    <LemonInputSelect
                        allowCustomValues={false}
                        placeholder="Click or type to see top pages"
                        loading={values.isLoading}
                        size="small"
                        mode="single"
                        value={values.pageUrl ? [values.pageUrl] : null}
                        onChange={(val: string[]) => actions.setPageUrl(val.length > 0 ? val[0] : null)}
                        options={options}
                        onInputChange={(val: string) => actions.setPageUrlSearchTerm(val)}
                        data-attr="page-url-search"
                        onFocus={() => actions.loadPages('')}
                        className="max-w-full"
                    />
                </div>
                <div>
                    <DateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={(fromDate, toDate) => setDates(fromDate, toDate)}
                    />
                </div>
            </div>
            <div className="flex items-center gap-2">
                <LearnMorePopover
                    title="Strip query parameters"
                    description="Remove query strings from URLs (e.g. '?utm_source=...'). This will match the base URL regardless of query parameters. For example, 'https://example.com/products' and 'https://example.com/products?id=123' will be treated as the same page, but 'https://example.com/products-new' will be treated as a different page."
                />
                <LemonSwitch
                    checked={values.stripQueryParams}
                    onChange={actions.toggleStripQueryParams}
                    label="Strip query parameters"
                    size="small"
                />
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
    query: any
    tileId: TileId
}): JSX.Element => {
    const { createInsightProps } = useValues(pageReportsLogic)

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
    const values = useValues(pageReportsLogic)

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

    return (
        <div className="space-y-2 mt-2">
            <PageUrlSearchHeader />

            {!values.hasPageUrl ? (
                <ProductIntroduction
                    productName="PAGE REPORTS"
                    thingName="page report"
                    description="Page Reports provide in-depth analytics for individual pages on your website. Use the search bar above to select a specific page and see detailed metrics."
                    isEmpty={true}
                    customHog={() => <XRayHog2 alt="X-ray hedgehog" className="w-60" />}
                />
            ) : (
                <>
                    {/* Trends Section */}
                    <Section title="Trends over time">
                        <div className="w-full min-h-[350px]">
                            <WebQuery
                                query={values.combinedMetricsQuery(dateFilter, compareFilter)}
                                showIntervalSelect={true}
                                tileId={TileId.PAGE_REPORTS_COMBINED_METRICS_CHART}
                                insightProps={values.createInsightProps(
                                    TileId.PAGE_REPORTS_COMBINED_METRICS_CHART,
                                    'combined'
                                )}
                                key={`combined-metrics-${values.pageUrl}`}
                            />
                        </div>
                    </Section>

                    {/* Page Paths Analysis Section */}
                    <Section title="Page Paths Analysis">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <SimpleTile
                                title="Entry Paths"
                                description="How users arrive at this page"
                                query={values.queries.entryPathsQuery}
                                tileId={TileId.PAGE_REPORTS_ENTRY_PATHS}
                            />

                            <SimpleTile
                                title="Exit Paths"
                                description="Where users go after viewing this page"
                                query={values.queries.exitPathsQuery}
                                tileId={TileId.PAGE_REPORTS_EXIT_PATHS}
                            />

                            <SimpleTile
                                title="Outbound Clicks"
                                description="External links users click on this page"
                                query={values.queries.outboundClicksQuery}
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
                                query={values.queries.channelsQuery}
                                tileId={TileId.PAGE_REPORTS_CHANNELS}
                            />

                            <SimpleTile
                                title="Referrers"
                                description="Websites referring traffic to this page"
                                query={values.queries.referrersQuery}
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
                                query={values.queries.deviceTypeQuery}
                                tileId={TileId.PAGE_REPORTS_DEVICE_TYPES}
                            />

                            <SimpleTile
                                title="Browsers"
                                description="Browsers used to access this page"
                                query={values.queries.browserQuery}
                                tileId={TileId.PAGE_REPORTS_BROWSERS}
                            />

                            <SimpleTile
                                title="Operating Systems"
                                description="Operating systems used to access this page"
                                query={values.queries.osQuery}
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
                                query={values.queries.countriesQuery}
                                tileId={TileId.PAGE_REPORTS_COUNTRIES}
                            />

                            <SimpleTile
                                title="Regions"
                                description="Regions where users access this page from"
                                query={values.queries.regionsQuery}
                                tileId={TileId.PAGE_REPORTS_REGIONS}
                            />

                            <SimpleTile
                                title="Cities"
                                description="Cities where users access this page from"
                                query={values.queries.citiesQuery}
                                tileId={TileId.PAGE_REPORTS_CITIES}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                            <SimpleTile
                                title="Timezones"
                                description="Timezones where users access this page from"
                                query={values.queries.timezonesQuery}
                                tileId={TileId.PAGE_REPORTS_TIMEZONES}
                            />

                            <SimpleTile
                                title="Languages"
                                description="Languages of users accessing this page"
                                query={values.queries.languagesQuery}
                                tileId={TileId.PAGE_REPORTS_LANGUAGES}
                            />
                        </div>
                    </Section>
                </>
            )}
        </div>
    )
}
