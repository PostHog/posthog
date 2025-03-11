import { IconExpand45, IconInfo, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { addProductIntentForCrossSell, ProductIntentContext } from 'lib/utils/product-intents'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    ChartDisplayType,
    InsightLogicProps,
    ProductKey,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { pageReportsLogic } from './pageReportsLogic'
import { WebQuery } from './tiles/WebAnalyticsTile'
import {
    DeviceTab,
    GeographyTab,
    PathTab,
    SourceTab,
    TabsTile,
    TileId,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    webAnalyticsLogic,
} from './webAnalyticsLogic'

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
    const { pageUrlSearchOptions, pageUrl } = useValues(pageReportsLogic)
    const { setPageUrl, setPageUrlSearchTerm } = useActions(pageReportsLogic)

    const placeholderUrl = pageUrlSearchOptions?.[0] ?? '/pricing'

    return (
        <div className="bg-bg-light p-4 rounded flex items-center gap-2 mb-4">
            <div className="flex-1">
                <h3 className="mb-2">Select a page to analyze</h3>
                <p className="text-muted mb-2">
                    Page Reports provide detailed analytics for a specific page on your website. Select a page to see
                    visitor behavior, traffic sources, and more.
                </p>
                <div className="flex gap-2">
                    <div className="flex-1">
                        <LemonInputSelect
                            mode="single"
                            allowCustomValues
                            placeholder={`e.g. ${placeholderUrl}`}
                            onInputChange={(e) => setPageUrlSearchTerm(e)}
                            value={pageUrl ? [pageUrl] : undefined}
                            onChange={(v) => setPageUrl(v[0] ?? null)}
                            options={
                                pageUrlSearchOptions?.map((page: string) => ({
                                    label: page,
                                    key: page,
                                })) ?? []
                            }
                        />
                    </div>
                    <LemonButton
                        type="secondary"
                        sideIcon={<IconOpenInNew />}
                        to={pageUrl ? urls.insightNew() : undefined}
                        targetBlank
                        disabledReason={!pageUrl ? 'Select a URL first' : undefined}
                    >
                        Open as insight
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

export const PageReports = (): JSX.Element => {
    const { tiles, dateFilter, shouldFilterTestAccounts, compareFilter, getNewInsightUrl } =
        useValues(webAnalyticsLogic)
    const { openModal, togglePropertyFilter } = useActions(webAnalyticsLogic)
    const { pageUrl, hasPageUrl } = useValues(pageReportsLogic)

    // Find the tiles
    const pathsTile = tiles.find((tile) => tile.tileId === TileId.PATHS) as TabsTile | undefined
    const sourcesTile = tiles.find((tile) => tile.tileId === TileId.SOURCES) as TabsTile | undefined
    const devicesTile = tiles.find((tile) => tile.tileId === TileId.DEVICES) as TabsTile | undefined
    const geographyTile = tiles.find((tile) => tile.tileId === TileId.GEOGRAPHY) as TabsTile | undefined

    // Get the queries for each tab
    const entryPathsQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.INITIAL_PATH)?.query
    const exitPathsQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.END_PATH)?.query
    const outboundClicksQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.EXIT_CLICK)?.query

    // Get source queries
    const channelsQuery = sourcesTile?.tabs.find((tab) => tab.id === SourceTab.CHANNEL)?.query
    const referrersQuery = sourcesTile?.tabs.find((tab) => tab.id === SourceTab.REFERRING_DOMAIN)?.query

    // Get device queries
    const deviceTypeQuery = devicesTile?.tabs.find((tab) => tab.id === DeviceTab.DEVICE_TYPE)?.query
    const browserQuery = devicesTile?.tabs.find((tab) => tab.id === DeviceTab.BROWSER)?.query
    const osQuery = devicesTile?.tabs.find((tab) => tab.id === DeviceTab.OS)?.query

    // Get geography queries
    const countriesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.COUNTRIES)?.query
    const regionsQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.REGIONS)?.query
    const citiesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.CITIES)?.query
    const timezonesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.TIMEZONES)?.query
    const languagesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.LANGUAGES)?.query

    // Create insight props for the queries
    const createInsightProps = (tileId: TileId, tabId?: string): InsightLogicProps => ({
        dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
        loadPriority: 0,
        dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })

    // Apply the page URL filter when it changes
    useEffect(() => {
        if (pageUrl) {
            togglePropertyFilter(PropertyFilterType.Event, '$pathname', pageUrl)
        }
    }, [pageUrl, togglePropertyFilter])

    // Create a combined query for all three metrics
    const combinedMetricsQuery: InsightVizNode<TrendsQuery> = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.UniqueUsers,
                    name: '$pageview',
                    custom_name: 'Unique visitors',
                },
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.TotalCount,
                    name: '$pageview',
                    custom_name: 'Page views',
                },
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.UniqueSessions,
                    name: '$pageview',
                    custom_name: 'Sessions',
                },
            ],
            interval: dateFilter.interval,
            dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                showLegend: true,
            },
            compareFilter,
            filterTestAccounts: shouldFilterTestAccounts,
            properties: [
                {
                    key: '$pathname',
                    value: pageUrl,
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        },
        hidePersonsModal: true,
        embedded: true,
    }

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
                            insightProps={createInsightProps(tileId, tabId)}
                        />
                    )}
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-2 mt-2">
            <PageUrlSearchHeader />

            {!hasPageUrl ? (
                <ProductIntroduction
                    productName="PAGE REPORTS"
                    thingName="page report"
                    description="Page Reports provide in-depth analytics for individual pages on your website. Use the search bar above to select a specific page and see detailed metrics."
                    isEmpty={true}
                    customHog={() => (
                        <img src="/static/assets/hedgehog/x-ray-hogs-02.png" alt="X-ray hedgehog" className="w-60" />
                    )}
                />
            ) : (
                <>
                    <LemonBanner type="success" className="mb-2">
                        <h3 className="font-semibold">Page Report: {pageUrl}</h3>
                    </LemonBanner>

                    {/* Trends Section */}
                    <Section title="Trends over time">
                        <div>
                            <div className="flex justify-between items-center mb-1">
                                <div className="flex gap-1">
                                    {getNewInsightUrl(TileId.GRAPHS, 'combined') && (
                                        <LemonButton
                                            icon={<IconOpenInNew />}
                                            size="small"
                                            to={getNewInsightUrl(TileId.GRAPHS, 'combined')}
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
                                </div>
                            </div>
                            <div>
                                <div className="w-full min-h-[350px]">
                                    <WebQuery
                                        query={combinedMetricsQuery}
                                        showIntervalSelect={true}
                                        tileId={TileId.GRAPHS}
                                        insightProps={createInsightProps(TileId.GRAPHS, 'combined')}
                                    />
                                </div>
                            </div>
                        </div>
                    </Section>

                    {/* Page Paths Analysis Section */}
                    <Section title="Page Paths Analysis">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <SimpleTile
                                title="Entry Paths"
                                description="How users arrive at this page"
                                query={entryPathsQuery}
                                tileId={TileId.PATHS}
                                tabId={PathTab.INITIAL_PATH}
                            />

                            <SimpleTile
                                title="Exit Paths"
                                description="Where users go after viewing this page"
                                query={exitPathsQuery}
                                tileId={TileId.PATHS}
                                tabId={PathTab.END_PATH}
                            />

                            <SimpleTile
                                title="Outbound Clicks"
                                description="External links users click on this page"
                                query={outboundClicksQuery}
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
                                query={channelsQuery}
                                tileId={TileId.SOURCES}
                                tabId={SourceTab.CHANNEL}
                            />

                            <SimpleTile
                                title="Referrers"
                                description="Websites referring traffic to this page"
                                query={referrersQuery}
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
                                query={deviceTypeQuery}
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.DEVICE_TYPE}
                            />

                            <SimpleTile
                                title="Browsers"
                                description="Browsers used to access this page"
                                query={browserQuery}
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.BROWSER}
                            />

                            <SimpleTile
                                title="Operating Systems"
                                description="Operating systems used to access this page"
                                query={osQuery}
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
                                query={countriesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.COUNTRIES}
                            />

                            <SimpleTile
                                title="Regions"
                                description="Regions where users access this page from"
                                query={regionsQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.REGIONS}
                            />

                            <SimpleTile
                                title="Cities"
                                description="Cities where users access this page from"
                                query={citiesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.CITIES}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                            <SimpleTile
                                title="Timezones"
                                description="Timezones where users access this page from"
                                query={timezonesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.TIMEZONES}
                            />

                            <SimpleTile
                                title="Languages"
                                description="Languages of users accessing this page"
                                query={languagesQuery}
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
