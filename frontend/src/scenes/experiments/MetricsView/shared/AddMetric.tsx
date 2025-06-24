import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { MAX_PRIMARY_METRICS, MAX_SECONDARY_METRICS } from './const'

export function AddPrimaryMetric(): JSX.Element {
    const { primaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const { openPrimaryMetricSourceModal } = useActions(experimentLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openPrimaryMetricSourceModal()
            }}
            disabledReason={
                primaryMetricsLengthWithSharedMetrics >= MAX_PRIMARY_METRICS
                    ? `You can only add up to ${MAX_PRIMARY_METRICS} primary metrics.`
                    : undefined
            }
        >
            Add primary metric
        </LemonButton>
    )
}

export function AddSecondaryMetric(): JSX.Element {
    const { secondaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const { openSecondaryMetricSourceModal } = useActions(experimentLogic)
    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openSecondaryMetricSourceModal()
            }}
            disabledReason={
                secondaryMetricsLengthWithSharedMetrics >= MAX_SECONDARY_METRICS
                    ? `You can only add up to ${MAX_SECONDARY_METRICS} secondary metrics.`
                    : undefined
            }
        >
            Add secondary metric
        </LemonButton>
    )
}
