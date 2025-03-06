import { IconChevronDown, IconTrending, IconWarning } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { getColorVar } from 'lib/colors'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { IconOpenInNew, IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { percentage, tryDecodeURIComponent, UnexpectedNeverError } from 'lib/utils'
import {
    COUNTRY_CODE_TO_LONG_NAME,
    countryCodeToFlag,
    LANGUAGE_CODE_TO_NAME,
    languageCodeToFlag,
} from 'lib/utils/geography/country'
import { useCallback, useMemo } from 'react'
import { NewActionButton } from 'scenes/actions/NewActionButton'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { GeographyTab, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { actionsModel } from '~/models/actionsModel'
import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
    DataVisualizationNode,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    WebAnalyticsOrderByFields,
    WebStatsBreakdown,
    WebVitalsPathBreakdownQuery,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps, ProductKey, PropertyFilterType } from '~/types'

import { HeatmapButton } from '../CrossSellButtons/HeatmapButton'
import { ReplayButton } from '../CrossSellButtons/ReplayButton'

const toUtcOffsetFormat = (value: number): string => {
    if (value === 0) {
        return 'UTC'
    }

    const integerPart = Math.floor(value)
    const sign = integerPart > 0 ? '+' : '-'

    // India has half-hour offsets, and Australia has 45-minute offsets, why?
    const decimalPart = value - integerPart
    const decimalPartAsMinutes = decimalPart * 60
    const formattedMinutes = decimalPartAsMinutes > 0 ? `:${decimalPartAsMinutes}` : ''

    // E.g. UTC-3, UTC, UTC+5:30, UTC+11:45
    return `UTC${sign}${integerPart}${formattedMinutes}`
}

type VariationCellProps = { isPercentage?: boolean; reverseColors?: boolean }
const VariationCell = (
    { isPercentage, reverseColors }: VariationCellProps = { isPercentage: false, reverseColors: false }
): QueryContextColumnComponent => {
    const formatNumber = (value: number): string =>
        isPercentage ? `${(value * 100).toFixed(1)}%` : value?.toLocaleString() ?? '(empty)'

    return function Cell({ value }) {
        const { compareFilter } = useValues(webAnalyticsLogic)

        if (!value) {
            return null
        }

        if (!Array.isArray(value)) {
            return <span>{String(value)}</span>
        }

        const [current, previous] = value as [number, number]

        const pctChangeFromPrevious =
            previous === 0 && current === 0 // Special case, render as flatline
                ? 0
                : current === null || !compareFilter || compareFilter.compare === false
                ? null
                : previous === null || previous === 0
                ? Infinity
                : current / previous - 1

        const trend =
            pctChangeFromPrevious === null
                ? null
                : pctChangeFromPrevious === 0
                ? { Icon: IconTrendingFlat, color: getColorVar('muted') }
                : pctChangeFromPrevious > 0
                ? {
                      Icon: IconTrending,
                      color: reverseColors ? getColorVar('danger') : getColorVar('success'),
                  }
                : {
                      Icon: IconTrendingDown,
                      color: reverseColors ? getColorVar('success') : getColorVar('danger'),
                  }

        // If current === previous, say "increased by 0%"
        const tooltip =
            pctChangeFromPrevious !== null
                ? `${current >= previous ? 'Increased' : 'Decreased'} by ${percentage(
                      Math.abs(pctChangeFromPrevious),
                      0
                  )} since last period (from ${formatNumber(previous)} to ${formatNumber(current)})`
                : null

        return (
            <div className={clsx({ 'pr-4': !trend })}>
                <Tooltip title={tooltip}>
                    <span>
                        {formatNumber(current)}&nbsp;
                        {trend && (
                            // eslint-disable-next-line react/forbid-dom-props
                            <span style={{ color: trend.color }}>
                                <trend.Icon color={trend.color} className="ml-1" />
                            </span>
                        )}
                    </span>
                </Tooltip>
            </div>
        )
    }
}

const BreakdownValueTitle: QueryContextColumnTitleComponent = (props) => {
    const { query } = props
    const { source } = query
    if (source.kind !== NodeKind.WebStatsTableQuery) {
        return null
    }
    const { breakdownBy } = source
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return <>Path</>
        case WebStatsBreakdown.InitialPage:
            return <>Initial Path</>
        case WebStatsBreakdown.ExitPage:
            return <>End Path</>
        case WebStatsBreakdown.ExitClick:
            return <>Exit Click</>
        case WebStatsBreakdown.ScreenName:
            return <>Screen Name</>
        case WebStatsBreakdown.InitialChannelType:
            return <>Initial Channel Type</>
        case WebStatsBreakdown.InitialReferringDomain:
            return <>Referring Domain</>
        case WebStatsBreakdown.InitialUTMSource:
            return <>UTM Source</>
        case WebStatsBreakdown.InitialUTMCampaign:
            return <>UTM Campaign</>
        case WebStatsBreakdown.InitialUTMMedium:
            return <>UTM Medium</>
        case WebStatsBreakdown.InitialUTMTerm:
            return <>UTM Term</>
        case WebStatsBreakdown.InitialUTMContent:
            return <>UTM Content</>
        case WebStatsBreakdown.Browser:
            return <>Browser</>
        case WebStatsBreakdown.OS:
            return <>OS</>
        case WebStatsBreakdown.Viewport:
            return <>Viewport</>
        case WebStatsBreakdown.DeviceType:
            return <>Device Type</>
        case WebStatsBreakdown.Country:
            return <>Country</>
        case WebStatsBreakdown.Region:
            return <>Region</>
        case WebStatsBreakdown.City:
            return <>City</>
        case WebStatsBreakdown.Timezone:
            return <>Timezone</>
        case WebStatsBreakdown.Language:
            return <>Language</>
        case WebStatsBreakdown.InitialUTMSourceMediumCampaign:
            return <>Source / Medium / Campaign</>
        default:
            throw new UnexpectedNeverError(breakdownBy)
    }
}

const BreakdownValueCell: QueryContextColumnComponent = (props) => {
    const { value, query } = props
    const { source } = query
    if (source.kind !== NodeKind.WebStatsTableQuery) {
        return null
    }
    const { breakdownBy } = source

    switch (breakdownBy) {
        case WebStatsBreakdown.ExitPage:
        case WebStatsBreakdown.InitialPage:
        case WebStatsBreakdown.Page: {
            if (typeof value !== 'string') {
                return <>{value}</>
            }
            const decoded = tryDecodeURIComponent(value)
            return <>{source.doPathCleaning ? parseAliasToReadable(decoded) : decoded}</>
        }
        case WebStatsBreakdown.Viewport:
            if (Array.isArray(value)) {
                const [width, height] = value
                return (
                    <>
                        {width}x{height}
                    </>
                )
            }
            break
        case WebStatsBreakdown.Country:
            if (typeof value === 'string') {
                const countryCode = value
                return (
                    <>
                        {countryCodeToFlag(countryCode)} {COUNTRY_CODE_TO_LONG_NAME[countryCode] || countryCode}
                    </>
                )
            }
            break
        case WebStatsBreakdown.Region:
            if (Array.isArray(value)) {
                const [countryCode, regionCode, regionName] = value
                return (
                    <>
                        {countryCodeToFlag(countryCode)} {COUNTRY_CODE_TO_LONG_NAME[countryCode] || countryCode} -{' '}
                        {regionName || regionCode}
                    </>
                )
            }
            break
        case WebStatsBreakdown.City:
            if (Array.isArray(value)) {
                const [countryCode, cityName] = value
                return (
                    <>
                        {countryCodeToFlag(countryCode)} {COUNTRY_CODE_TO_LONG_NAME[countryCode] || countryCode} -{' '}
                        {cityName}
                    </>
                )
            }
            break
        case WebStatsBreakdown.Timezone:
            if (typeof value === 'number') {
                return <>{toUtcOffsetFormat(value)}</>
            }
            break
        case WebStatsBreakdown.Language:
            if (typeof value === 'string') {
                const [languageCode, countryCode] = value.split('-')

                // Locales are complicated, the country code might be hidden in the second part
                // of the locale
                const parsedCountryCode = countryCode?.match(/([A-Z]{2})/)?.[0] ?? ''
                return (
                    <>
                        {countryCodeToFlag(parsedCountryCode) ?? languageCodeToFlag(languageCode)}&nbsp;
                        {LANGUAGE_CODE_TO_NAME[languageCode] || languageCode}
                    </>
                )
            }
            break
        case WebStatsBreakdown.DeviceType:
            if (typeof value === 'string') {
                return <PropertyIcon.WithLabel property="$device_type" value={value} />
            }
            break
        case WebStatsBreakdown.Browser:
            if (typeof value === 'string') {
                return <PropertyIcon.WithLabel property="$browser" value={value} />
            }
            break
        case WebStatsBreakdown.OS:
            if (typeof value === 'string') {
                return <PropertyIcon.WithLabel property="$os" value={value} />
            }
            break
    }

    if (typeof value === 'string') {
        return <>{value}</>
    }
    return null
}

const SortableCell = (name: string, orderByField: WebAnalyticsOrderByFields): QueryContextColumnTitleComponent =>
    function SortableCell() {
        const { tablesOrderBy } = useValues(webAnalyticsLogic)
        const { setTablesOrderBy } = useActions(webAnalyticsLogic)

        const isSortedByMyField = tablesOrderBy?.[0] === orderByField
        const isAscending = tablesOrderBy?.[1] === 'ASC'

        // Toggle between DESC, ASC, and no sort, in this order
        const onClick = useCallback(() => {
            if (!isSortedByMyField || isAscending) {
                setTablesOrderBy(orderByField, 'DESC')
            } else {
                setTablesOrderBy(orderByField, 'ASC')
            }
        }, [isAscending, isSortedByMyField, setTablesOrderBy])

        return (
            <span onClick={onClick} className="group cursor-pointer inline-flex items-center">
                {name}
                <IconChevronDown
                    fontSize="20px"
                    className={clsx('-mr-1 ml-1 text-muted-alt opacity-0 group-hover:opacity-100', {
                        'text-primary opacity-100': isSortedByMyField,
                        'rotate-180': isSortedByMyField && isAscending,
                    })}
                />
            </span>
        )
    }

export const webStatsBreakdownToPropertyName = (
    breakdownBy: WebStatsBreakdown
):
    | { key: string; type: PropertyFilterType.Person | PropertyFilterType.Event | PropertyFilterType.Session }
    | undefined => {
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return { key: '$pathname', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialPage:
            return { key: '$entry_pathname', type: PropertyFilterType.Session }
        case WebStatsBreakdown.ExitPage:
            return { key: '$end_pathname', type: PropertyFilterType.Session }
        case WebStatsBreakdown.ExitClick:
            return { key: '$last_external_click_url', type: PropertyFilterType.Session }
        case WebStatsBreakdown.ScreenName:
            return { key: '$screen_name', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialChannelType:
            return { key: '$channel_type', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialReferringDomain:
            return { key: '$entry_referring_domain', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMSource:
            return { key: '$entry_utm_source', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMCampaign:
            return { key: '$entry_utm_campaign', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMMedium:
            return { key: '$entry_utm_medium', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMContent:
            return { key: '$entry_utm_content', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMTerm:
            return { key: '$entry_utm_term', type: PropertyFilterType.Session }
        case WebStatsBreakdown.Browser:
            return { key: '$browser', type: PropertyFilterType.Event }
        case WebStatsBreakdown.OS:
            return { key: '$os', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Viewport:
            return { key: '$viewport', type: PropertyFilterType.Event }
        case WebStatsBreakdown.DeviceType:
            return { key: '$device_type', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Country:
            return { key: '$geoip_country_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Region:
            return { key: '$geoip_subdivision_1_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.City:
            return { key: '$geoip_city_name', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Timezone:
            return { key: '$timezone', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Language:
            return { key: '$geoip_language', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialUTMSourceMediumCampaign:
            return undefined
        default:
            throw new UnexpectedNeverError(breakdownBy)
    }
}

export const webAnalyticsDataTableQueryContext: QueryContext = {
    columns: {
        breakdown_value: {
            renderTitle: BreakdownValueTitle,
            render: BreakdownValueCell,
        },
        bounce_rate: {
            renderTitle: SortableCell('Bounce Rate', WebAnalyticsOrderByFields.BounceRate),
            render: VariationCell({ isPercentage: true, reverseColors: true }),
            align: 'right',
        },
        views: {
            renderTitle: SortableCell('Views', WebAnalyticsOrderByFields.Views),
            render: VariationCell(),
            align: 'right',
        },
        clicks: {
            renderTitle: SortableCell('Clicks', WebAnalyticsOrderByFields.Clicks),
            render: VariationCell(),
            align: 'right',
        },
        visitors: {
            renderTitle: SortableCell('Visitors', WebAnalyticsOrderByFields.Visitors),
            render: VariationCell(),
            align: 'right',
        },
        average_scroll_percentage: {
            renderTitle: SortableCell('Average Scroll', WebAnalyticsOrderByFields.AverageScrollPercentage),
            render: VariationCell({ isPercentage: true }),
            align: 'right',
        },
        scroll_gt80_percentage: {
            renderTitle: SortableCell('Deep Scroll Rate', WebAnalyticsOrderByFields.ScrollGt80Percentage),
            render: VariationCell({ isPercentage: true }),
            align: 'right',
        },
        total_conversions: {
            renderTitle: SortableCell('Total Conversions', WebAnalyticsOrderByFields.TotalConversions),
            render: VariationCell(),
            align: 'right',
        },
        unique_conversions: {
            renderTitle: SortableCell('Unique Conversions', WebAnalyticsOrderByFields.UniqueConversions),
            render: VariationCell(),
            align: 'right',
        },
        conversion_rate: {
            renderTitle: SortableCell('Conversion Rate', WebAnalyticsOrderByFields.ConversionRate),
            render: VariationCell({ isPercentage: true }),
            align: 'right',
        },
        converting_users: {
            renderTitle: SortableCell('Converting Users', WebAnalyticsOrderByFields.ConvertingUsers),
            render: VariationCell(),
            align: 'right',
        },
        action_name: {
            title: 'Action',
        },
        cross_sell: {
            title: ' ',
            render: ({ record, query }: { record: any; query: DataTableNode | DataVisualizationNode }) => {
                const dateRange = (query.source as any)?.dateRange
                const breakdownBy = (query.source as any)?.breakdownBy
                const value = record[0] ?? ''

                return (
                    <div className="flex flex-row items-center justify-end">
                        <ReplayButton
                            date_from={dateRange?.date_from}
                            date_to={dateRange?.date_to}
                            breakdownBy={breakdownBy}
                            value={value}
                        />
                        <HeatmapButton breakdownBy={breakdownBy} value={value} />
                    </div>
                )
            },
            align: 'right',
        },
    },
}

type QueryWithInsightProps<Q extends QuerySchema> = { query: Q; insightProps: InsightLogicProps }

export const WebStatsTrendTile = ({
    query,
    showIntervalTile,
    insightProps,
}: QueryWithInsightProps<InsightVizNode> & { showIntervalTile?: boolean }): JSX.Element => {
    const { togglePropertyFilter, setInterval } = useActions(webAnalyticsLogic)
    const {
        hasCountryFilter,
        dateFilter: { interval },
    } = useValues(webAnalyticsLogic)
    const worldMapPropertyName = webStatsBreakdownToPropertyName(WebStatsBreakdown.Country)?.key

    const onWorldMapClick = useCallback(
        (breakdownValue: string) => {
            if (!worldMapPropertyName) {
                return
            }
            togglePropertyFilter(PropertyFilterType.Event, worldMapPropertyName, breakdownValue, {
                geographyTab: hasCountryFilter ? undefined : GeographyTab.REGIONS,
            })
        },
        [togglePropertyFilter, worldMapPropertyName, hasCountryFilter]
    )

    const context = useMemo((): QueryContext => {
        return {
            ...webAnalyticsDataTableQueryContext,
            onDataPointClick({ breakdown }, data) {
                if (breakdown === 'string' && data && (data.count > 0 || data.aggregated_value > 0)) {
                    onWorldMapClick(breakdown)
                }
            },
            insightProps: {
                ...insightProps,
                query,
            },
        }
    }, [onWorldMapClick, insightProps])

    return (
        <div className="border rounded bg-surface-primary flex-1 flex flex-col">
            {showIntervalTile && (
                <div className="flex flex-row items-center justify-end m-2 mr-4">
                    <div className="flex flex-row items-center">
                        <span className="mr-2">Group by</span>
                        <IntervalFilterStandalone
                            interval={interval}
                            onIntervalChange={setInterval}
                            options={[
                                { value: 'hour', label: 'Hour' },
                                { value: 'day', label: 'Day' },
                                { value: 'week', label: 'Week' },
                                { value: 'month', label: 'Month' },
                            ]}
                        />
                    </div>
                </div>
            )}
            <Query query={query} readOnly={true} context={context} />
        </div>
    )
}

export const WebStatsTableTile = ({
    query,
    breakdownBy,
    insightProps,
    control,
}: QueryWithInsightProps<DataTableNode> & {
    breakdownBy: WebStatsBreakdown
    control?: JSX.Element
}): JSX.Element => {
    const { togglePropertyFilter } = useActions(webAnalyticsLogic)

    const { key, type } = webStatsBreakdownToPropertyName(breakdownBy) || {}

    const onClick = useCallback(
        (breakdownValue: string | null) => {
            if (!key || !type) {
                return
            }

            togglePropertyFilter(type, key, breakdownValue)
        },
        [togglePropertyFilter, type, key]
    )

    const context = useMemo((): QueryContext => {
        const rowProps: QueryContext['rowProps'] = (record: unknown) => {
            // `onClick` won't know how to handle the breakdown value if these don't exist,
            // so let's prevent from `onClick` from being set up in the first place to avoid a noop click
            if (!key || !type) {
                return {}
            }

            // Tricky to calculate because the breakdown is a computed value rather than a DB column, make it non-filterable for now
            if (breakdownBy === WebStatsBreakdown.Language || breakdownBy === WebStatsBreakdown.Timezone) {
                return {}
            }

            const breakdownValue = getBreakdownValue(record, breakdownBy)
            if (breakdownValue === undefined) {
                return {}
            }

            return { onClick: () => onClick(breakdownValue) }
        }

        return {
            ...webAnalyticsDataTableQueryContext,
            insightProps,
            rowProps,
        }
    }, [onClick, insightProps])

    return (
        <div className="border rounded bg-surface-primary flex-1 flex flex-col">
            {control != null && <div className="flex flex-row items-center justify-end m-2 mr-4">{control}</div>}
            <Query query={query} readOnly={true} context={context} />
        </div>
    )
}

const getBreakdownValue = (record: unknown, breakdownBy: WebStatsBreakdown): string | null | undefined => {
    if (typeof record !== 'object' || !record || !('result' in record)) {
        return undefined
    }
    const result = record.result
    if (!Array.isArray(result)) {
        return undefined
    }
    // assume that the first element is the value
    const breakdownValue = result[0]

    switch (breakdownBy) {
        case WebStatsBreakdown.Country:
            if (Array.isArray(breakdownValue)) {
                return breakdownValue[0]
            }
            break
        case WebStatsBreakdown.Region:
            if (Array.isArray(breakdownValue)) {
                return breakdownValue[1]
            }
            break
        case WebStatsBreakdown.City:
            if (Array.isArray(breakdownValue)) {
                return breakdownValue[1]
            }
            break
    }

    if (breakdownValue === null) {
        return null // null is a valid value, as opposed to undefined which signals that there isn't a valid value
    }

    if (typeof breakdownValue !== 'string') {
        return undefined
    }
    return breakdownValue
}

export const WebGoalsTile = ({ query, insightProps }: QueryWithInsightProps<DataTableNode>): JSX.Element | null => {
    const { actions, actionsLoading } = useValues(actionsModel)
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    if (actionsLoading) {
        return null
    }

    if (!actions.length) {
        return (
            <ProductIntroduction
                productName="Actions"
                productKey={ProductKey.ACTIONS}
                thingName="action"
                isEmpty={true}
                description="Use actions to combine events that you want to have tracked together or to make detailed Autocapture events easier to reuse."
                docsURL="https://posthog.com/docs/data/actions"
                actionElementOverride={
                    <NewActionButton onSelectOption={() => updateHasSeenProductIntroFor(ProductKey.ACTIONS, true)} />
                }
            />
        )
    }

    return (
        <div className="border rounded bg-surface-primary flex-1">
            <div className="flex flex-row-reverse p-2">
                <LemonButton to={urls.actions()} sideIcon={<IconOpenInNew />} type="secondary" size="small">
                    Manage actions
                </LemonButton>
            </div>
            <Query query={query} readOnly={true} context={{ ...webAnalyticsDataTableQueryContext, insightProps }} />
        </div>
    )
}

export const WebExternalClicksTile = ({
    query,
    insightProps,
}: QueryWithInsightProps<DataTableNode>): JSX.Element | null => {
    const { shouldStripQueryParams } = useValues(webAnalyticsLogic)
    const { setShouldStripQueryParams } = useActions(webAnalyticsLogic)
    return (
        <div className="border rounded bg-surface-primary flex-1 flex flex-col">
            <div className="flex flex-row items-center justify-end m-2 mr-4">
                <div className="flex flex-row items-center deprecated-space-x-2">
                    <LemonSwitch
                        label="Strip query parameters"
                        checked={shouldStripQueryParams}
                        onChange={setShouldStripQueryParams}
                        className="h-full"
                    />
                </div>
            </div>
            <Query query={query} readOnly={true} context={{ ...webAnalyticsDataTableQueryContext, insightProps }} />
        </div>
    )
}

export const WebVitalsPathBreakdownTile = ({
    query,
    insightProps,
}: QueryWithInsightProps<WebVitalsPathBreakdownQuery>): JSX.Element => {
    const { isPathCleaningEnabled } = useValues(webAnalyticsLogic)
    const { setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)

    return (
        <div>
            <div className="flex flex-row items-center gap-1 m-2">
                <h3 className="text-lg font-semibold">Path Breakdown</h3>
                {!isPathCleaningEnabled && (
                    <Tooltip
                        title={
                            <span>
                                Path Breakdown is more useful when path cleaning is turned on.{' '}
                                <Link onClick={() => setIsPathCleaningEnabled(true)}>Enable it.</Link>
                            </span>
                        }
                        interactive
                    >
                        <IconWarning className="mb-2" fontSize="18" />
                    </Tooltip>
                )}
            </div>
            <Query query={query} readOnly context={{ ...webAnalyticsDataTableQueryContext, insightProps }} />
        </div>
    )
}

export const WebQuery = ({
    query,
    showIntervalSelect,
    control,
    insightProps,
}: QueryWithInsightProps<QuerySchema> & {
    showIntervalSelect?: boolean
    control?: JSX.Element
}): JSX.Element => {
    if (query.kind === NodeKind.DataTableNode && query.source.kind === NodeKind.WebStatsTableQuery) {
        return (
            <WebStatsTableTile
                query={query}
                breakdownBy={query.source.breakdownBy}
                insightProps={insightProps}
                control={control}
            />
        )
    }

    if (query.kind === NodeKind.DataTableNode && query.source.kind === NodeKind.WebExternalClicksTableQuery) {
        return <WebExternalClicksTile query={query} insightProps={insightProps} />
    }

    if (query.kind === NodeKind.InsightVizNode) {
        return <WebStatsTrendTile query={query} showIntervalTile={showIntervalSelect} insightProps={insightProps} />
    }

    if (query.kind === NodeKind.DataTableNode && query.source.kind === NodeKind.WebGoalsQuery) {
        return <WebGoalsTile query={query} insightProps={insightProps} />
    }

    if (query.kind === NodeKind.WebVitalsPathBreakdownQuery) {
        return <WebVitalsPathBreakdownTile query={query} insightProps={insightProps} />
    }

    return <Query query={query} readOnly={true} context={{ ...webAnalyticsDataTableQueryContext, insightProps }} />
}
