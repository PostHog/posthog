import { IconGraph, IconPlus } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import {
    METRIC_CONTEXTS,
    type MetricContext,
} from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'

import { DEFAULT_METRICS_HELP_TEXT, useAddMetric } from './EmptyMetricsPanel'

export function QuillEmptyMetricsPanel({
    helpText,
    isLaunched,
    showHelpText = true,
    onAddMetric,
}: {
    helpText?: string
    isLaunched?: boolean
    showHelpText?: boolean
    onAddMetric?: (metricType: MetricContext['type']) => void
}): JSX.Element {
    const addMetric = useAddMetric(onAddMetric)

    return (
        <Empty data-attr="experiment-metrics-empty">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-experiments-light)">
                        <IconGraph />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>No metrics yet</EmptyTitle>
                <EmptyDescription>
                    {!isLaunched && showHelpText
                        ? (helpText ?? DEFAULT_METRICS_HELP_TEXT)
                        : 'A primary metric tracks your main hypothesis. Secondary metrics provide additional context and detect side effects.'}
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center">
                <Button variant="primary" onClick={() => addMetric(METRIC_CONTEXTS.primary)}>
                    <IconPlus />
                    Add primary metric
                </Button>
                <Button variant="outline" onClick={() => addMetric(METRIC_CONTEXTS.secondary)}>
                    <IconPlus />
                    Add secondary metric
                </Button>
            </EmptyContent>
        </Empty>
    )
}
