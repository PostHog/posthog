import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WebAnalyticsPropertyFilters } from '~/queries/schema'

export const WebPropertyFilters = ({
    webAnalyticsFilters,
    setWebAnalyticsFilters,
}: {
    webAnalyticsFilters: WebAnalyticsPropertyFilters
    setWebAnalyticsFilters: (filters: WebAnalyticsPropertyFilters) => void
}): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <PropertyFilters
            taxonomicGroupTypes={
                featureFlags[FEATURE_FLAGS.SESSION_TABLE_PROPERTY_FILTERS]
                    ? [
                          TaxonomicFilterGroupType.SessionProperties,
                          TaxonomicFilterGroupType.EventProperties,
                          TaxonomicFilterGroupType.PersonProperties,
                      ]
                    : [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]
            }
            onChange={(filters) => setWebAnalyticsFilters(filters.filter(isEventPersonOrSessionPropertyFilter))}
            propertyFilters={webAnalyticsFilters}
            pageKey="web-analytics"
            eventNames={['$pageview', '$pageleave', '$autocapture']}
        />
    )
}
