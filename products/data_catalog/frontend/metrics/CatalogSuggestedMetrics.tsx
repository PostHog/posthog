import { useValues } from 'kea'

import { Item, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { UsageScanWindow } from '../components/UsageScanWindow'
import { GovernanceSectionFailed } from '../governance/GovernanceSectionFailed'
import { usageLogic } from '../usageLogic'
import { CatalogMetricsLayer } from './CatalogMetricsLayer'
import { catalogSuggestedMetricsLogic } from './catalogSuggestedMetricsLogic'
import { CatalogSuggestedMetricsTable } from './CatalogSuggestedMetricsTable'

const SKELETON_ROWS = 3
// pinned: autocapture reads the data-attr value to tell this list from the lists of catalog metrics
const DATA_ATTR = 'data-catalog-metrics-layer-suggested'

export function CatalogSuggestedMetrics(): JSX.Element | null {
    const { latest, latestLoadFailed, failureReasons } = useValues(usageLogic)
    const { visibleSuggestions } = useValues(catalogSuggestedMetricsLogic)

    if (latestLoadFailed) {
        return (
            <Item variant="outline" tone="destructive">
                <ItemContent>
                    <ItemDescription>
                        Couldn't load the suggested metrics. Refresh the page, and if it keeps happening contact
                        support.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }
    if (latest === null) {
        return (
            <div className="flex flex-col gap-2" aria-busy="true">
                {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                    <Skeleton key={index} className="h-10 w-full" />
                ))}
            </div>
        )
    }
    if (failureReasons.uncovered) {
        return (
            <CatalogMetricsLayer title="Suggested" dataAttr={DATA_ATTR}>
                <GovernanceSectionFailed reason={failureReasons.uncovered} />
            </CatalogMetricsLayer>
        )
    }
    // The catalog metrics follow this list, so an empty list shows nothing and leaves the space to them.
    if (visibleSuggestions.length === 0) {
        return null
    }

    return (
        <CatalogMetricsLayer
            title="Suggested"
            count={visibleSuggestions.length}
            description={
                <div className="flex flex-wrap gap-x-1">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        These measures come up often in queries and charts, but no metric defines them yet. Open one to
                        create a metric from its query.
                    </Text>
                    {latest !== 'none' && <UsageScanWindow scan={latest} />}
                </div>
            }
            dataAttr={DATA_ATTR}
        >
            <CatalogSuggestedMetricsTable />
        </CatalogMetricsLayer>
    )
}
