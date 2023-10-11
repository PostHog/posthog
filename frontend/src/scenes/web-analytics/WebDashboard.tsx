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

const NumericCell: QueryContextColumnComponent = ({ value }) => {
    return (
        <div className="w-full text-right">
            <span className="flex-1 text-right">{String(value)}</span>
        </div>
    )
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
        views: {
            title: 'Views',
            render: NumericCell,
        },
        visitors: {
            title: 'Visitors',
            render: NumericCell,
        },
    },
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    const { tiles, webAnalyticsFilters } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters } = useActions(webAnalyticsLogic)
    return (
        <div>
            <div className="sticky top-0 bg-white z-20 pt-2">
                <PropertyFilters
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    onChange={(filters) => setWebAnalyticsFilters(filters.filter(isEventPropertyFilter))}
                    propertyFilters={webAnalyticsFilters}
                    pageKey={'web-analytics'}
                />
                <div className={'bg-border h-px w-full mt-2'} />
            </div>
            <div className="mt-2 grid grid-cols-1 md:grid-cols-12 gap-4">
                {tiles.map((tile, i) => {
                    if ('query' in tile) {
                        const { query, title, layout } = tile
                        return (
                            <div
                                key={i}
                                className={`col-span-1 row-span-1 md:col-span-${layout.colSpan ?? 6} md:row-span-${
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
        </div>
    )
}
