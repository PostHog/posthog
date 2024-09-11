import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { WebAnalyticsPropertyFilters } from '~/queries/schema'

export const WebPropertyFilters = ({
    webAnalyticsFilters,
    setWebAnalyticsFilters,
}: {
    webAnalyticsFilters: WebAnalyticsPropertyFilters
    setWebAnalyticsFilters: (filters: WebAnalyticsPropertyFilters) => void
}): JSX.Element => {
    return (
        <>
            <PropertyFilters
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.SessionProperties,
                ]}
                onChange={(filters) => setWebAnalyticsFilters(filters.filter(isEventPersonOrSessionPropertyFilter))}
                propertyFilters={webAnalyticsFilters}
                pageKey="web-analytics"
                eventNames={['$pageview']}
            />
        </>
    )
}
