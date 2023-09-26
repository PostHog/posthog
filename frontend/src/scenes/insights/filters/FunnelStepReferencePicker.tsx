import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FunnelStepReference } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'
import { FunnelsFilter } from '~/queries/schema'

export function FunnelStepReferencePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnelStepReference } = (insightFilter || {}) as FunnelsFilter

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
            value={funnelStepReference || FunnelStepReference.total}
            onChange={(stepRef) => stepRef && updateInsightFilter({ funnelStepReference: stepRef })}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-step-reference-selector"
            options={options}
        />
    )
}
