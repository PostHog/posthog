import { MaxErrorTrackingSearchResponse } from '@posthog/query-frontend/schema/schema-assistant-error-tracking'

import { ErrorTrackingUniversalFiltersDisplay } from 'lib/components/Cards/InsightCard/ErrorTrackingUniversalFiltersDisplay'

export function ErrorTrackingFiltersSummary({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element {
    return <ErrorTrackingUniversalFiltersDisplay filters={filters} className="px-2 pb-2 space-y-1.5" />
}
