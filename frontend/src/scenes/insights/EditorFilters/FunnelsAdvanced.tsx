import { useValues, useActions, useMountedLogic } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelStepReference, StepOrderValue, EditorFilterProps } from '~/types'
import { FunnelStepOrderPicker } from '../views/Funnels/FunnelStepOrderPicker'
import { FunnelExclusionsFilter } from '../filters/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../filters/FunnelStepReferencePicker'
import { funnelCommandLogic } from '../views/Funnels/funnelCommandLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PureField } from 'lib/forms/Field'

export function FunnelsAdvanced({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))
    const { setFilters, setStepReference } = useActions(funnelLogic(insightProps))
    useMountedLogic(funnelCommandLogic)

    return (
        <div className="space-y-4">
            <PureField
                label="Step order"
                info={
                    <ul className="list-disc pl-4">
                        <li>
                            <b>Sequential</b> - Step B must happen after Step A, but any number events can happen
                            between A and B.
                        </li>
                        <li>
                            <b>Strict order</b> - Step B must happen directly after Step A without any events in
                            between.
                        </li>
                        <li>
                            <b>Any order</b> - Steps can be completed in any sequence.
                        </li>
                    </ul>
                }
            >
                <FunnelStepOrderPicker />
            </PureField>
            <PureField label="Conversion rate calculation">
                <FunnelStepReferencePicker />
            </PureField>

            <PureField
                label="Exclusion steps"
                info={
                    <>
                        Exclude {aggregationTargetLabel.plural}{' '}
                        {filters.aggregation_group_type_index != undefined ? 'that' : 'who'} completed the specified
                        event between two specific steps. Note that these {aggregationTargetLabel.plural} will be{' '}
                        <b>completely excluded from the entire funnel</b>.
                    </>
                }
            >
                <FunnelExclusionsFilter />
            </PureField>

            {!!advancedOptionsUsedCount && (
                <div className="mt-4">
                    <LemonButton
                        status="danger"
                        onClick={() => {
                            setStepReference(FunnelStepReference.total)
                            setFilters({
                                funnel_order_type: StepOrderValue.ORDERED,
                                exclusions: [],
                            })
                        }}
                    >
                        Reset advanced options
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
