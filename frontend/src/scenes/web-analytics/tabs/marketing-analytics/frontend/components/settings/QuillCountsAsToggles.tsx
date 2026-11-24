import { useId } from 'react'

import { Checkbox, Field, FieldLabel } from '@posthog/quill'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import { revenueDisabledReason } from './conversionGoalFlags'

export function QuillCountsAsToggles({
    goal,
    onChange,
    disabledReason,
}: {
    goal: ConversionGoalFilter
    onChange: (goal: ConversionGoalFilter) => void
    disabledReason?: string | null
}): JSX.Element {
    const revenueId = useId()
    const customerId = useId()

    return (
        <div className="flex flex-col gap-1">
            <Field orientation="horizontal" className="w-fit">
                <Checkbox
                    id={revenueId}
                    checked={!!goal.counts_as_revenue}
                    onCheckedChange={(counts_as_revenue: boolean) => onChange({ ...goal, counts_as_revenue })}
                    disabledReason={disabledReason || revenueDisabledReason(goal)}
                />
                <FieldLabel htmlFor={revenueId}>Revenue</FieldLabel>
            </Field>
            <Field orientation="horizontal" className="w-fit">
                <Checkbox
                    id={customerId}
                    checked={!!goal.counts_as_customer}
                    onCheckedChange={(counts_as_customer: boolean) => onChange({ ...goal, counts_as_customer })}
                    disabledReason={disabledReason}
                />
                <FieldLabel htmlFor={customerId}>Customer</FieldLabel>
            </Field>
        </div>
    )
}
