import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { StepOrderValue } from '~/types'

interface StepOption {
    key?: string
    label: string
    value: StepOrderValue
    disabledReason?: string
}

export function FunnelStepOrderPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter, series } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnelOrderType } = (insightFilter || {}) as FunnelsFilter

    const hasOptionalSteps = !!series?.some((step) => step.optionalInFunnel)

    const options: StepOption[] = [
        {
            label: 'Sequential',
            value: StepOrderValue.ORDERED,
        },
        {
            label: 'Strict order',
            value: StepOrderValue.STRICT,
        },
        {
            label: 'Any order',
            value: StepOrderValue.UNORDERED,
            disabledReason: hasOptionalSteps
                ? 'Any order is not supported with optional steps. Remove the optional steps first.'
                : undefined,
        },
    ]

    return (
        <LemonSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={funnelOrderType || StepOrderValue.ORDERED}
            onChange={(stepOrder) => stepOrder && updateInsightFilter({ funnelOrderType: stepOrder })}
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
