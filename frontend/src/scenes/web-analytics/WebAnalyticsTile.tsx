import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { DataTableNode, InsightVizNode, NodeKind, WebStatsBreakdown } from '~/queries/schema'
import { UnexpectedNeverError } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { GeographyTab, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { useCallback, useMemo } from 'react'
import { Query } from '~/queries/Query/Query'
import { countryCodeToFlag, countryCodeToName } from 'scenes/insights/views/WorldMap'
import { PropertyFilterType } from '~/types'
import { ChartDisplayType } from '~/types'

const PercentageCell: QueryContextColumnComponent = ({ value }) => {
    if (typeof value === 'number') {
        return <span>{`${(value * 100).toFixed(1)}%`}</span>
    } else {
        return null
    }
}

const NumericCell: QueryContextColumnComponent = ({ value }) => {
    return <span>{typeof value === 'number' ? value.toLocaleString() : String(value)}</span>
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
        case WebStatsBreakdown.DeviceType:
            return <>Device Type</>
        case WebStatsBreakdown.Country:
            return <>Country</>
        case WebStatsBreakdown.Region:
            return <>Region</>
        case WebStatsBreakdown.City:
            return <>City</>
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
        case WebStatsBreakdown.Country:
            if (typeof value === 'string') {
                const countryCode = value
                return (
                    <>
                        {countryCodeToFlag(countryCode)} {countryCodeToName[countryCode] || countryCode}
                    </>
                )
            }
            break
        case WebStatsBreakdown.Region:
            if (Array.isArray(value)) {
                const [countryCode, regionCode, regionName] = value
                return (
                    <>
                        {countryCodeToFlag(countryCode)} {countryCodeToName[countryCode] || countryCode} -{' '}
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
                        {countryCodeToFlag(countryCode)} {countryCodeToName[countryCode] || countryCode} - {cityName}
                    </>
                )
            }
            break
    }

    if (typeof value === 'string') {
        return <>{value}</>
    } else {
        return null
    }
}

export const webStatsBreakdownToPropertyName = (
    breakdownBy: WebStatsBreakdown
): { key: string; type: PropertyFilterType.Person | PropertyFilterType.Event } => {
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return { key: '$pathname', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialPage:
            return { key: '$initial_pathname', type: PropertyFilterType.Person }
        case WebStatsBreakdown.InitialReferringDomain:
            return { key: '$initial_referring_domain', type: PropertyFilterType.Person }
        case WebStatsBreakdown.InitialUTMSource:
            return { key: '$initial_utm_source', type: PropertyFilterType.Person }
        case WebStatsBreakdown.InitialUTMCampaign:
            return { key: '$initial_utm_campaign', type: PropertyFilterType.Person }
        case WebStatsBreakdown.InitialUTMMedium:
            return { key: '$initial_utm_medium', type: PropertyFilterType.Person }
        case WebStatsBreakdown.InitialUTMContent:
            return { key: '$initial_utm_content', type: PropertyFilterType.Person }
        case WebStatsBreakdown.InitialUTMTerm:
            return { key: '$initial_utm_term', type: PropertyFilterType.Person }
        case WebStatsBreakdown.Browser:
            return { key: '$browser', type: PropertyFilterType.Event }
        case WebStatsBreakdown.OS:
            return { key: '$os', type: PropertyFilterType.Event }
        case WebStatsBreakdown.DeviceType:
            return { key: '$device_type', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Country:
            return { key: '$geoip_country_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Region:
            return { key: '$geoip_subdivision_1_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.City:
            return { key: '$geoip_city_name', type: PropertyFilterType.Event }
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
            title: 'Bounce Rate',
            render: PercentageCell,
            align: 'right',
        },
        views: {
            title: 'Views',
            render: NumericCell,
            align: 'right',
        },
        visitors: {
            title: 'Visitors',
            render: NumericCell,
            align: 'right',
        },
    },
}

export const WebStatsTrendTile = ({ query }: { query: InsightVizNode }): JSX.Element => {
    const { togglePropertyFilter, setGeographyTab } = useActions(webAnalyticsLogic)
    const { hasCountryFilter } = useValues(webAnalyticsLogic)
    const { key: worldMapPropertyName } = webStatsBreakdownToPropertyName(WebStatsBreakdown.Country)
    const onWorldMapClick = useCallback(
        (breakdownValue: string) => {
            togglePropertyFilter(PropertyFilterType.Event, worldMapPropertyName, breakdownValue)
            if (!hasCountryFilter) {
                // if we just added a country filter, switch to the region tab, as the world map will not be useful
                setGeographyTab(GeographyTab.REGIONS)
            }
        },
        [togglePropertyFilter, worldMapPropertyName]
    )

    const context = useMemo((): QueryContext => {
        return {
            ...webAnalyticsDataTableQueryContext,
            chartRenderingMetadata: {
                [ChartDisplayType.WorldMap]: {
                    countryProps: (countryCode, values) => {
                        return {
                            onClick:
                                values && (values.count > 0 || values.aggregated_value > 0)
                                    ? () => onWorldMapClick(countryCode)
                                    : undefined,
                        }
                    },
                },
            },
        }
    }, [onWorldMapClick])

    return <Query query={query} readOnly={true} context={context} />
}

export const WebStatsTableTile = ({
    query,
    breakdownBy,
}: {
    query: DataTableNode
    breakdownBy: WebStatsBreakdown
}): JSX.Element => {
    const { togglePropertyFilter } = useActions(webAnalyticsLogic)
    const { key, type } = webStatsBreakdownToPropertyName(breakdownBy)

    const onClick = useCallback(
        (breakdownValue: string) => {
            togglePropertyFilter(type, key, breakdownValue)
        },
        [togglePropertyFilter, type, key]
    )

    const context = useMemo((): QueryContext => {
        const rowProps: QueryContext['rowProps'] = (record: unknown) => {
            const breakdownValue = getBreakdownValue(record, breakdownBy)
            if (breakdownValue === undefined) {
                return {}
            }
            return {
                onClick: () => onClick(breakdownValue),
            }
        }
        return {
            ...webAnalyticsDataTableQueryContext,
            rowProps,
        }
    }, [onClick])

    return <Query query={query} readOnly={true} context={context} />
}

const getBreakdownValue = (record: unknown, breakdownBy: WebStatsBreakdown): string | undefined => {
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

    if (typeof breakdownValue !== 'string') {
        return undefined
    }
    return breakdownValue
}
