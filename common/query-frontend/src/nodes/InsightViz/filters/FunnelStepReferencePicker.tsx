import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { funnelDataLogic } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelDataLogic'
import { FunnelsFilter } from '@posthog/query-frontend/schema/schema-general'

import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelStepReference } from '~/types'

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
