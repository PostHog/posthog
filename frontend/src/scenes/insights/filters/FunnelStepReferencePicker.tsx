import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FunnelStepReference } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'

export function FunnelStepReferencePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { stepReference } = useValues(funnelLogic(insightProps))
    const { setStepReference } = useActions(funnelLogic(insightProps))

    const options = [
        {
            value: FunnelStepReference.total,
            label: 'Overall conversion',
        },
        {
            value: FunnelStepReference.previous,
            label: 'Relative to previous step',
        },
    ]

    return (
        <LemonSelect
            value={stepReference || FunnelStepReference.total}
            onChange={(stepRef) => stepRef && setStepReference(stepRef)}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-step-reference-selector"
            options={options}
        />
    )
}
