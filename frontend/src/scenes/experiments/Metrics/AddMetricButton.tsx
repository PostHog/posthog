import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { MetricContext } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'
import { metricSourceModalLogic } from 'products/experiments/frontend/modals/MetricSourceModal/metricSourceModalLogic'

export const AddMetricButton = ({ metricContext }: { metricContext: MetricContext }): JSX.Element => {
    const { openMetricSourceModal } = useActions(metricSourceModalLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openMetricSourceModal(metricContext)
            }}
        >
            Add {metricContext.type} metric
        </LemonButton>
    )
}
