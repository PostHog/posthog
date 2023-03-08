import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelsFilterType, FunnelStepReference } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'

export function FunnelStepReferencePickerDataExploration(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return <FunnelStepReferencePickerComponent setFilters={updateInsightFilter} {...insightFilter} />
}

export function FunnelStepReferencePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { stepReference } = useValues(funnelLogic(insightProps))
    const { setStepReference } = useActions(funnelLogic(insightProps))

    return (
        <FunnelStepReferencePickerComponent
            funnel_step_reference={stepReference}
            setFilters={({ funnel_step_reference }) => funnel_step_reference && setStepReference(funnel_step_reference)}
        />
    )
}

type FunnelStepReferencePickerComponentProps = {
    setFilters: (filters: Partial<FunnelsFilterType>) => void
} & FunnelsFilterType

export function FunnelStepReferencePickerComponent({
    funnel_step_reference,
    setFilters,
}: FunnelStepReferencePickerComponentProps): JSX.Element | null {
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
            value={funnel_step_reference || FunnelStepReference.total}
            onChange={(stepRef) => stepRef && setFilters({ funnel_step_reference: stepRef })}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-step-reference-selector"
            options={options}
        />
    )
}
