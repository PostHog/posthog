import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'

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
                {tiles.map(({ query, layout }, i) => (
                    <div
                        key={i}
                        className={`col-span-${layout.colSpan ?? 6} row-span-${
                            layout.rowSpan ?? 1
                        } min-h-100 flex flex-col`}
                    >
                        <Query query={query} readOnly={true} />
                    </div>
                ))}
            </div>
        </>
    )
}
