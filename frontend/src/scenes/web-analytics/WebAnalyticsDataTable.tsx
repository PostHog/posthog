import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { DataTableNode, NodeKind, WebStatsBreakdown } from '~/queries/schema'
import { UnexpectedNeverError } from 'lib/utils'
import { useActions } from 'kea'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { useCallback, useMemo } from 'react'
import { Query } from '~/queries/Query/Query'
import { countryCodeToFlag, countryCodeToName } from 'scenes/insights/views/WorldMap'

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

export const webStatsBreakdownToPropertyName = (breakdownBy: WebStatsBreakdown): string => {
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return '$pathname'
        case WebStatsBreakdown.InitialPage:
            return '$initial_pathname'
        case WebStatsBreakdown.InitialReferringDomain:
            return '$initial_referrer'
        case WebStatsBreakdown.InitialUTMSource:
            return '$initial_utm_source'
        case WebStatsBreakdown.InitialUTMCampaign:
            return '$initial_utm_campaign'
        case WebStatsBreakdown.Browser:
            return '$browser'
        case WebStatsBreakdown.OS:
            return '$os'
        case WebStatsBreakdown.DeviceType:
            return '$device_type'
        case WebStatsBreakdown.Country:
            return '$geoip_country_code'
        case WebStatsBreakdown.Region:
            return '$geoip_subdivision_1_code'
        case WebStatsBreakdown.City:
            return '$geoip_city_name'
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

export const WebStatsTableTile = ({
    query,
    breakdownBy,
}: {
    query: DataTableNode
    breakdownBy: WebStatsBreakdown
}): JSX.Element => {
    const { togglePropertyFilter } = useActions(webAnalyticsLogic)
    const propertyName = webStatsBreakdownToPropertyName(breakdownBy)

    const onClick = useCallback(
        (breakdownValue: string) => {
            togglePropertyFilter(propertyName, breakdownValue)
        },
        [togglePropertyFilter, propertyName]
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
