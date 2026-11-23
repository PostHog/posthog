import { useActions } from 'kea'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import { DEFAULT_METRICS_FILTERS, metricsLogic } from '../metricsLogic'
import { DEFAULT_METRIC_CHECKS_FILTER, catalogMetricsLogic } from './catalogMetricsLogic'

export function CatalogMetricsNoMatch(): JSX.Element {
    const { setFilters } = useActions(metricsLogic)
    const { setChecksFilter } = useActions(catalogMetricsLogic)
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>No metrics match</EmptyTitle>
                <EmptyDescription>Change the search or the filters to see more metrics.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                        setFilters(DEFAULT_METRICS_FILTERS)
                        setChecksFilter(DEFAULT_METRIC_CHECKS_FILTER)
                    }}
                    data-attr="data-catalog-metrics-show-all"
                >
                    Show all metrics
                </Button>
            </EmptyContent>
        </Empty>
    )
}
