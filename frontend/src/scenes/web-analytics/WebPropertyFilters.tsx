import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPropertyOrPersonPropertyFilter } from 'lib/components/PropertyFilters/utils'
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
        <PropertyFilters
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]}
            onChange={(filters) => setWebAnalyticsFilters(filters.filter(isEventPropertyOrPersonPropertyFilter))}
            propertyFilters={webAnalyticsFilters}
            pageKey="web-analytics"
            eventNames={['$pageview', '$pageleave', '$autocapture']}
            propertyAllowList={{
                [TaxonomicFilterGroupType.EventProperties]: [
                    '$pathname',
                    '$host',
                    '$browser',
                    '$os',
                    '$device_type',
                    '$geoip_country_code',
                    '$geoip_subdivision_1_code',
                    '$geoip_city_name',
                    // re-enable after https://github.com/PostHog/posthog-js/pull/875 is merged
                    // '$client_session_initial_pathname',
                    // '$client_session_initial_referring_host',
                    // '$client_session_initial_utm_source',
                    // '$client_session_initial_utm_campaign',
                    // '$client_session_initial_utm_medium',
                    // '$client_session_initial_utm_content',
                    // '$client_session_initial_utm_term',
                ],
                [TaxonomicFilterGroupType.PersonProperties]: [
                    '$initial_pathname',
                    '$initial_referring_domain',
                    '$initial_utm_source',
                    '$initial_utm_campaign',
                    '$initial_utm_medium',
                    '$initial_utm_content',
                    '$initial_utm_term',
                ],
            }}
        />
    )
}
