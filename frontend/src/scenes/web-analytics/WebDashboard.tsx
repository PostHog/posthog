import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { QueryContext, QueryContextColumnComponent } from '~/queries/schema'
import { useCallback } from 'react'

const PercentageCell: QueryContextColumnComponent = ({ value }) => {
    if (typeof value === 'number') {
        return (
            <div className="w-full text-right">
                <span className="flex-1 text-right">{`${(value * 100).toFixed(1)}%`}</span>
            </div>
        )
    } else {
        return null
    }
}

const ClickablePropertyCell: QueryContextColumnComponent = (props) => {
    const { columnName, value } = props
    const { togglePropertyFilter } = useActions(webAnalyticsLogic)
    let propertyName: string
    switch (columnName) {
        case 'pathname':
            propertyName = '$pathname'
            break
        default:
            return null
    }

    const onClick = useCallback(() => {
        togglePropertyFilter(propertyName, value)
    }, [togglePropertyFilter, propertyName, value])

    return <a onClick={onClick}>{value}</a>
}

const queryContext: QueryContext = {
    columns: {
        bounce_rate: {
            title: 'Bounce Rate',
            render: PercentageCell,
        },
        pathname: {
            title: 'Path',
            render: ClickablePropertyCell,
        },
    },
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    const { tiles, webAnalyticsFilters } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters } = useActions(webAnalyticsLogic)
    return (
        <>
            <PropertyFilters
                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                onChange={(filters) => setWebAnalyticsFilters(filters.filter(isEventPropertyFilter))}
                propertyFilters={webAnalyticsFilters}
                pageKey={'web-analytics'}
            />
            <div className="grid grid-cols-12 gap-4">
                {tiles.map((tile, i) => {
                    if ('query' in tile) {
                        const { query, title, layout } = tile
                        return (
                            <div
                                key={i}
                                className={`col-span-${layout.colSpan ?? 6} row-span-${
                                    layout.rowSpan ?? 1
                                } min-h-100 flex flex-col`}
                            >
                                {title && <h2>{title}</h2>}
                                <Query query={query} readOnly={true} context={queryContext} />
                            </div>
                        )
                    } else {
                        return null
                    }
                })}
            </div>
        </>
    )
}
