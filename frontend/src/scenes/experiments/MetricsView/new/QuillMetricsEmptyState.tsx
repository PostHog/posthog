import { IconGraph } from '@posthog/icons'
import {
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { QuillAddMetricButton } from '~/scenes/experiments/Metrics/QuillAddMetricButton'

import { METRIC_CONTEXTS } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'

export const PRIMARY_METRICS_EMPTY =
    'Primary metrics represent the main goal of the experiment and directly measure if your hypothesis was successful.'
export const SECONDARY_METRICS_EMPTY =
    'Secondary metrics provide additional context and help detect unintended side effects.'

export function QuillMetricsEmptyState({ isSecondary }: { isSecondary: boolean }): JSX.Element {
    const type = isSecondary ? 'secondary' : 'primary'
    return (
        <Empty data-attr={`experiment-${type}-metrics-empty`}>
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-experiments-light)">
                        <IconGraph />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>{`No ${type} metrics yet`}</EmptyTitle>
                <EmptyDescription>{isSecondary ? SECONDARY_METRICS_EMPTY : PRIMARY_METRICS_EMPTY}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <QuillAddMetricButton
                    metricContext={isSecondary ? METRIC_CONTEXTS.secondary : METRIC_CONTEXTS.primary}
                />
            </EmptyContent>
        </Empty>
    )
}
