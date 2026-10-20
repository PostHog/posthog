import { Field, FieldLabel, Input } from '@posthog/quill'

import { QuillLabeledSwitch } from 'lib/components/QuillLabeledSwitch/QuillLabeledSwitch'

import { MAX_BREAKDOWN_LIMIT, MIN_BREAKDOWN_LIMIT } from './GlobalBreakdownOptionsMenu'
import type { BreakdownOptionsProps } from './GlobalBreakdownOptionsMenu'

export function QuillGlobalBreakdownOptionsMenu({
    isTrends,
    breakdownLimit,
    breakdownHideOtherAggregation,
    setBreakdownHideOtherAggregation,
    onCommitLimit,
}: BreakdownOptionsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {isTrends && (
                <QuillLabeledSwitch
                    checked={!breakdownHideOtherAggregation}
                    onChange={() => setBreakdownHideOtherAggregation(!breakdownHideOtherAggregation)}
                    label='Group remaining values under "Other"'
                    tooltip={
                        <>
                            If you have over {breakdownLimit} breakdown options, the smallest ones are aggregated under
                            the label "Other". Use this toggle to show/hide the "Other" option.
                        </>
                    }
                />
            )}
            <Field orientation="horizontal" className="w-auto items-center gap-2">
                <FieldLabel htmlFor="breakdown-limit" className="font-normal">
                    Breakdown limit
                </FieldLabel>
                {/* Uncontrolled so the user can clear the field while retyping; the limit commits on blur or Enter. */}
                <Input
                    key={breakdownLimit}
                    id="breakdown-limit"
                    type="number"
                    min={MIN_BREAKDOWN_LIMIT}
                    max={MAX_BREAKDOWN_LIMIT}
                    defaultValue={breakdownLimit}
                    className="w-20"
                    onBlur={(event) => onCommitLimit(event.currentTarget)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            event.currentTarget.blur()
                        }
                    }}
                />
            </Field>
        </div>
    )
}
