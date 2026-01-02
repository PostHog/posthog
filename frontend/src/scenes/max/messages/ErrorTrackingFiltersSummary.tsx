import { ErrorTrackingUniversalFiltersDisplay } from 'lib/components/Cards/InsightCard/ErrorTrackingUniversalFiltersDisplay'

import { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'

export function ErrorTrackingFiltersSummary({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element {
    return <ErrorTrackingUniversalFiltersDisplay filters={filters} />
}
