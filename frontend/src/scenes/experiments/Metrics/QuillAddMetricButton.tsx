import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { MetricContext } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'
import { metricSourceModalLogic } from 'products/experiments/frontend/modals/MetricSourceModal/metricSourceModalLogic'

export const QuillAddMetricButton = ({
    metricContext,
    variant = 'outline',
}: {
    metricContext: MetricContext
    variant?: 'outline' | 'primary'
}): JSX.Element => {
    const { openMetricSourceModal } = useActions(metricSourceModalLogic)

    return (
        <Button variant={variant} onClick={() => openMetricSourceModal(metricContext)}>
            <IconPlus />
            Add {metricContext.type} metric
        </Button>
    )
}
