import { useValues, useActions } from 'kea'
import { QueryEditorFilterProps } from '~/types'
import { FunnelStepOrderPicker } from '../views/Funnels/FunnelStepOrderPicker'
import { FunnelExclusionsFilterDataExploration } from '../filters/FunnelExclusionsFilter/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../filters/FunnelStepReferencePicker'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PureField } from 'lib/forms/Field'
import { Noun } from '~/models/groupsModel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function FunnelsAdvanced({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { querySource, aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return (
        <div className="space-y-4">
            <PureField label="Step order" info={<StepOrderInfo />}>
                <FunnelStepOrderPicker />
            </PureField>
            <PureField label="Conversion rate calculation">
                <FunnelStepReferencePicker />
            </PureField>

            <PureField
                label="Exclusion steps"
                info={
                    <ExclusionStepsInfo
                        aggregationTargetLabel={aggregationTargetLabel}
                        aggregation_group_type_index={querySource?.aggregation_group_type_index}
                    />
                }
            >
                <FunnelExclusionsFilterDataExploration />
            </PureField>

            {!!advancedOptionsUsedCount && (
                <div className="mt-4">
                    <LemonButton
                        status="danger"
                        onClick={() => {
                            updateInsightFilter({
                                funnel_order_type: undefined,
                                funnel_step_reference: undefined,
                                exclusions: undefined,
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

function StepOrderInfo(): JSX.Element {
    return (
        <ul className="list-disc pl-4">
            <li>
                <b>Sequential</b> - Step B must happen after Step A, but any number events can happen between A and B.
            </li>
            <li>
                <b>Strict order</b> - Step B must happen directly after Step A without any events in between.
            </li>
            <li>
                <b>Any order</b> - Steps can be completed in any sequence.
            </li>
        </ul>
    )
}

type ExclusionStepsInfoProps = {
    aggregationTargetLabel: Noun
    aggregation_group_type_index?: number
}

function ExclusionStepsInfo({
    aggregationTargetLabel,
    aggregation_group_type_index,
}: ExclusionStepsInfoProps): JSX.Element {
    return (
        <>
            Exclude {aggregationTargetLabel.plural} {aggregation_group_type_index != undefined ? 'that' : 'who'}{' '}
            completed the specified event between two specific steps. Note that these {aggregationTargetLabel.plural}{' '}
            will be <b>completely excluded from the entire funnel</b>.
        </>
    )
}
