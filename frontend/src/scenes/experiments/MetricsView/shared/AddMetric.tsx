import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { EXPERIMENT_MAX_PRIMARY_METRICS, EXPERIMENT_MAX_SECONDARY_METRICS } from 'scenes/experiments/constants'
import { modalsLogic } from 'scenes/experiments/modalsLogic'

export function AddPrimaryMetric(): JSX.Element {
    const { primaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const { openPrimaryMetricSourceModal } = useActions(modalsLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openPrimaryMetricSourceModal()
            }}
            disabledReason={
                primaryMetricsLengthWithSharedMetrics >= EXPERIMENT_MAX_PRIMARY_METRICS
                    ? `You can only add up to ${EXPERIMENT_MAX_PRIMARY_METRICS} primary metrics.`
                    : undefined
            }
        >
            Add primary metric
        </LemonButton>
    )
}

export function AddSecondaryMetric(): JSX.Element {
    const { secondaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const { openSecondaryMetricSourceModal } = useActions(modalsLogic)
    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openSecondaryMetricSourceModal()
            }}
            disabledReason={
                secondaryMetricsLengthWithSharedMetrics >= EXPERIMENT_MAX_SECONDARY_METRICS
                    ? `You can only add up to ${EXPERIMENT_MAX_SECONDARY_METRICS} secondary metrics.`
                    : undefined
            }
        >
            Add secondary metric
        </LemonButton>
    )
}
