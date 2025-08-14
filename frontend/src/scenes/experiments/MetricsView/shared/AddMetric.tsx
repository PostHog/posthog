import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { useMetricLimits } from 'scenes/experiments/hooks/useMetricLimits'
import { modalsLogic } from 'scenes/experiments/modalsLogic'

export function AddPrimaryMetric(): JSX.Element {
    const { primaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const { openPrimaryMetricSourceModal } = useActions(modalsLogic)
    const { primary: primaryLimit } = useMetricLimits()

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openPrimaryMetricSourceModal()
            }}
            disabledReason={
                primaryMetricsLengthWithSharedMetrics >= primaryLimit
                    ? `You can only add up to ${primaryLimit} primary metrics.`
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
    const { secondary: secondaryLimit } = useMetricLimits()
    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openSecondaryMetricSourceModal()
            }}
            disabledReason={
                secondaryMetricsLengthWithSharedMetrics >= secondaryLimit
                    ? `You can only add up to ${secondaryLimit} secondary metrics.`
                    : undefined
            }
        >
            Add secondary metric
        </LemonButton>
    )
}
