import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { metricsLogic } from '../metricsLogic'
import { usageLogic } from '../usageLogic'
import { MetricsView, catalogMetricsLogic } from './catalogMetricsLogic'

const VIEW_LABELS: Record<MetricsView, string> = {
    defined: 'Defined',
    suggested: 'Suggested',
}

const VIEWS: MetricsView[] = ['defined', 'suggested']

export function CatalogMetricsViewToggle(): JSX.Element | null {
    const { view } = useValues(catalogMetricsLogic)
    const { setView } = useActions(catalogMetricsLogic)
    const { allMetrics, metricsLoadState } = useValues(metricsLogic)
    const { proposedRows, latest } = useValues(usageLogic)

    // A link can open the suggested view before a scan has a suggestion, and the toggle is then the way back.
    if (proposedRows.length === 0 && view !== 'suggested') {
        return null
    }

    const counts: Record<MetricsView, number | null> = {
        defined: metricsLoadState === 'loaded' ? allMetrics.length : null,
        suggested: latest === null ? null : proposedRows.length,
    }

    return (
        <ToggleGroup
            variant="default"
            aria-label="Show"
            value={[view]}
            onValueChange={(value: string[]) => value[0] && setView(value[0] as MetricsView)}
        >
            {VIEWS.map((option) => (
                <ToggleGroupItem key={option} value={option} data-attr={`data-catalog-metrics-view-${option}`}>
                    {VIEW_LABELS[option]}
                    {counts[option] !== null && (
                        <span translate="no" className="tabular-nums text-muted-foreground">
                            {counts[option]}
                        </span>
                    )}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
