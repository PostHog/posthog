import { RecordingsUniversalFiltersDisplay } from 'lib/components/Cards/InsightCard/RecordingsUniversalFiltersDisplay'

import { RecordingUniversalFilters } from '~/types'

export function RecordingsFiltersSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element {
    return <RecordingsUniversalFiltersDisplay filters={filters} />
}
