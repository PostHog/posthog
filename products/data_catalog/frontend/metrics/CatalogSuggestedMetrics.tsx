import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { UsageScanWindow } from '../components/UsageScanWindow'
import { usageLogic } from '../usageLogic'
import { CatalogMetricsLayer } from './CatalogMetricsLayer'
import { catalogSuggestedMetricsLogic } from './catalogSuggestedMetricsLogic'
import { CatalogSuggestedMetricsTable } from './CatalogSuggestedMetricsTable'

// pinned: autocapture reads the data-attr value to tell this list from the lists of catalog metrics
const DATA_ATTR = 'data-catalog-metrics-layer-suggested'

export function CatalogSuggestedMetrics(): JSX.Element | null {
    const { latest, latestLoadFailed } = useValues(usageLogic)
    const { visibleSuggestions } = useValues(catalogSuggestedMetricsLogic)

    // The list shows only when it has rows, so a team with no suggestions sees no trace of it: no skeleton
    // while the scan loads and no notice when the scan or its load fails. The Usage tab reports a failed scan.
    if (latestLoadFailed || visibleSuggestions.length === 0) {
        return null
    }

    return (
        <CatalogMetricsLayer
            title="Suggested"
            count={visibleSuggestions.length}
            description={
                <div className="flex flex-wrap gap-x-1">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        These measures are computed often in queries and charts, but no metric defines them yet. Open
                        one to create a metric, so later queries and charts reuse its definition.
                    </Text>
                    {latest && latest !== 'none' && <UsageScanWindow scan={latest} />}
                </div>
            }
            dataAttr={DATA_ATTR}
        >
            <CatalogSuggestedMetricsTable />
        </CatalogMetricsLayer>
    )
}
