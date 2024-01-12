import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema'
import { FunnelStepReference } from '~/types'

export function FunnelStepReferencePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnel_step_reference } = (insightFilter || {}) as FunnelsFilter

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
            onChange={(stepRef) => stepRef && updateInsightFilter({ funnel_step_reference: stepRef })}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-step-reference-selector"
            options={options}
        />
    )
}
