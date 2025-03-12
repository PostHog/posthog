import { IconExpand45, IconInfo, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconOpenInNew } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Popover } from 'lib/lemon-ui/Popover'
import { addProductIntentForCrossSell, ProductIntentContext } from 'lib/utils/product-intents'
import { useState } from 'react'

import { InsightLogicProps } from '~/types'
import { ProductKey } from '~/types'

import { pageReportsLogic } from './pageReportsLogic'
import { WebQuery } from './tiles/WebAnalyticsTile'
import { DeviceTab, GeographyTab, PathTab, SourceTab, TileId, webAnalyticsLogic } from './webAnalyticsLogic'

// Extended interface for pageReportsLogic values
interface PageReportsLogicValues {
    pageUrl: string | null
    pageUrlSearchTerm: string
    isInitialLoad: boolean
    pagesLoading: boolean
    hasPageUrl: boolean
    isLoading: boolean
    pageUrlSearchOptionsWithCount: { url: string; count: number }[]
    stripQueryParams: boolean
    // Queries object
    queries: {
        entryPathsQuery: any
        exitPathsQuery: any
        outboundClicksQuery: any
        channelsQuery: any
        referrersQuery: any
        deviceTypeQuery: any
        browserQuery: any
        osQuery: any
        countriesQuery: any
        regionsQuery: any
        citiesQuery: any
        timezonesQuery: any
        languagesQuery: any
    }
    // Helper functions
    createInsightProps: (tileId: TileId, tabId?: string) => InsightLogicProps
    // Combined metrics query
    combinedMetricsQuery: any
}

// Extended interface for pageReportsLogic actions
interface PageReportsLogicActions {
    setPageUrl: (url: string | string[] | null) => void
    setPageUrlSearchTerm: (searchTerm: string) => void
    loadPages: (searchTerm?: string) => void
    toggleStripQueryParams: () => void
}

// LearnMorePopover component
interface LearnMorePopoverProps {
    url?: string
    title: string
    description: string | JSX.Element
}

const LearnMorePopover = ({ url, title, description }: LearnMorePopoverProps): JSX.Element => {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <div className="p-4">
                    <div className="flex flex-row w-full">
                        <h2 className="flex-1">{title}</h2>
                        <LemonButton
                            targetBlank
                            type="tertiary"
                            onClick={() => setIsOpen(false)}
                            size="small"
                            icon={<IconX />}
                        />
                    </div>
                    <div className="text-sm text-gray-700">{description}</div>
                    {url && (
                        <div className="flex justify-end mt-4">
                            <LemonButton
                                to={url}
                                onClick={() => setIsOpen(false)}
                                targetBlank={true}
                                sideIcon={<IconOpenInNew />}
                            >
                                Learn more
                            </LemonButton>
                        </div>
                    )}
                </div>
            }
        >
            <LemonButton onClick={() => setIsOpen(!isOpen)} size="small" icon={<IconInfo />} className="ml-1" />
        </Popover>
    )
}

// URL Search Header component
function PageUrlSearchHeader(): JSX.Element {
    const values = useValues(pageReportsLogic) as unknown as PageReportsLogicValues
    const actions = useActions(pageReportsLogic) as unknown as PageReportsLogicActions
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
                <LemonSwitch
                    checked={values.stripQueryParams}
                    onChange={actions.toggleStripQueryParams}
                    label="Strip query parameters"
                    size="small"
                />
                <span className="text-muted text-xs">Remove query strings from URLs (e.g. "?utm_source=...")</span>
            </div>
        </div>
    )
}

export const PageReports = (): JSX.Element => {
    const { getNewInsightUrl } = useValues(webAnalyticsLogic)
    const { openModal } = useActions(webAnalyticsLogic)
    const values = useValues(pageReportsLogic) as unknown as PageReportsLogicValues

    // Section component for consistent styling
    const Section = ({ title, children }: { title: string; children: React.ReactNode }): JSX.Element => (
        <>
            <div className="flex items-center gap-2 mb-2">
                <h2 className="text-xl font-semibold">{title}</h2>
            </div>
            {children}
            <LemonDivider className="my-4" />
        </>
    )

    // SimpleTile component for consistent styling
    const SimpleTile = ({
        title,
        description,
        query,
        tileId,
        tabId,
    }: {
        title: string
        description: string
        query: any
        tileId: TileId
        tabId: string
    }): JSX.Element => {
        const insightUrl = getNewInsightUrl(tileId, tabId)

        return (
            <div>
                <div className="flex justify-between items-center mb-1">
                    <div className="flex items-center">
                        <h3 className="text-base font-semibold m-0">{title}</h3>
                        <LearnMorePopover title={title} description={description} />
                    </div>
                    <div className="flex gap-1">
                        {insightUrl && (
                            <LemonButton
                                icon={<IconOpenInNew />}
                                size="small"
                                to={insightUrl}
                                onClick={() => {
                                    void addProductIntentForCrossSell({
                                        from: ProductKey.WEB_ANALYTICS,
                                        to: ProductKey.PRODUCT_ANALYTICS,
                                        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                                    })
                                }}
                                tooltip="Open as new Insight"
                            />
                        )}
                        <LemonButton
                            icon={<IconExpand45 />}
                            size="small"
                            onClick={() => openModal(tileId, tabId)}
                            tooltip="Show more"
                        />
                    </div>
                </div>
                <div>
                    {query && (
                        <WebQuery
                            query={query}
                            showIntervalSelect={false}
                            tileId={tileId}
                            insightProps={values.createInsightProps(tileId, tabId)}
                            key={`${tileId}-${tabId}-${values.pageUrl}`}
                        />
                    )}
                    {!query && <div className="text-muted text-center p-4">No data available for this query</div>}
                </div>
            </div>
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
                                query={values.combinedMetricsQuery}
                                showIntervalSelect={true}
                                tileId={TileId.GRAPHS}
                                insightProps={values.createInsightProps(TileId.GRAPHS, 'combined')}
                                key={`combined-metrics-${values.pageUrl}`}
                            />
                            <LemonButton
                                key="open-insight-button"
                                to={getNewInsightUrl(TileId.GRAPHS, 'combined')}
                                icon={<IconOpenInNew />}
                                size="small"
                                type="secondary"
                                onClick={() => {
                                    void addProductIntentForCrossSell({
                                        from: ProductKey.WEB_ANALYTICS,
                                        to: ProductKey.PRODUCT_ANALYTICS,
                                        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                                    })
                                }}
                            >
                                Open as new Insight
                            </LemonButton>
                        </div>
                    </Section>

                    {/* Page Paths Analysis Section */}
                    <Section title="Page Paths Analysis">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <SimpleTile
                                title="Entry Paths"
                                description="How users arrive at this page"
                                query={values.queries.entryPathsQuery}
                                tileId={TileId.PATHS}
                                tabId={PathTab.INITIAL_PATH}
                            />

                            <SimpleTile
                                title="Exit Paths"
                                description="Where users go after viewing this page"
                                query={values.queries.exitPathsQuery}
                                tileId={TileId.PATHS}
                                tabId={PathTab.END_PATH}
                            />

                            <SimpleTile
                                title="Outbound Clicks"
                                description="External links users click on this page"
                                query={values.queries.outboundClicksQuery}
                                tileId={TileId.PATHS}
                                tabId={PathTab.EXIT_CLICK}
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
                                tileId={TileId.SOURCES}
                                tabId={SourceTab.CHANNEL}
                            />

                            <SimpleTile
                                title="Referrers"
                                description="Websites referring traffic to this page"
                                query={values.queries.referrersQuery}
                                tileId={TileId.SOURCES}
                                tabId={SourceTab.REFERRING_DOMAIN}
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
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.DEVICE_TYPE}
                            />

                            <SimpleTile
                                title="Browsers"
                                description="Browsers used to access this page"
                                query={values.queries.browserQuery}
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.BROWSER}
                            />

                            <SimpleTile
                                title="Operating Systems"
                                description="Operating systems used to access this page"
                                query={values.queries.osQuery}
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.OS}
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
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.COUNTRIES}
                            />

                            <SimpleTile
                                title="Regions"
                                description="Regions where users access this page from"
                                query={values.queries.regionsQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.REGIONS}
                            />

                            <SimpleTile
                                title="Cities"
                                description="Cities where users access this page from"
                                query={values.queries.citiesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.CITIES}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                            <SimpleTile
                                title="Timezones"
                                description="Timezones where users access this page from"
                                query={values.queries.timezonesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.TIMEZONES}
                            />

                            <SimpleTile
                                title="Languages"
                                description="Languages of users accessing this page"
                                query={values.queries.languagesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.LANGUAGES}
                            />
                        </div>
                    </Section>
                </>
            )}
        </div>
    )
}
