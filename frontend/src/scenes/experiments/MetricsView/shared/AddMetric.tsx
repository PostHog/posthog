import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { modalsLogic } from 'scenes/experiments/modalsLogic'

export function AddPrimaryMetric(): JSX.Element {
    const { openPrimaryMetricSourceModal } = useActions(modalsLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openPrimaryMetricSourceModal()
            }}
        >
            Add primary metric
        </LemonButton>
    )
}

export function AddSecondaryMetric(): JSX.Element {
    const { openSecondaryMetricSourceModal } = useActions(modalsLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openSecondaryMetricSourceModal()
            }}
        >
            Add secondary metric
        </LemonButton>
    )
}
