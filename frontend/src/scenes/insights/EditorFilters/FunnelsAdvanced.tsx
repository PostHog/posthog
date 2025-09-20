import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { Noun } from '~/models/groupsModel'
import { EditorFilterProps } from '~/types'

import { FunnelExclusionsFilter } from '../filters/FunnelExclusionsFilter/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../filters/FunnelStepReferencePicker'
import { FunnelStepOrderPicker } from '../views/Funnels/FunnelStepOrderPicker'

export function FunnelsAdvanced({ insightProps }: EditorFilterProps): JSX.Element {
    const { querySource, aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const { compareFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateCompareFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <div className="deprecated-space-y-4">
            <LemonField.Pure label="Step order" info={<StepOrderInfo />}>
                <FunnelStepOrderPicker />
            </LemonField.Pure>
            <LemonField.Pure label="Conversion rate calculation">
                <FunnelStepReferencePicker />
            </LemonField.Pure>

            <LemonField.Pure label="Compare to date range">
                <CompareFilter compareFilter={compareFilter} updateCompareFilter={updateCompareFilter} />
            </LemonField.Pure>

            <LemonField.Pure
                label="Exclusion steps"
                info={
                    <ExclusionStepsInfo
                        aggregationTargetLabel={aggregationTargetLabel}
                        aggregation_group_type_index={querySource?.aggregation_group_type_index}
                    />
                }
            >
                <FunnelExclusionsFilter />
            </LemonField.Pure>

            {!!advancedOptionsUsedCount && (
                <div className="mt-4">
                    <LemonButton
                        status="danger"
                        onClick={() => {
                            updateInsightFilter({
                                funnelOrderType: undefined,
                                funnelStepReference: undefined,
                                exclusions: undefined,
                            })
                            updateCompareFilter({ compare: false, compare_to: undefined })
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
    aggregation_group_type_index?: number | null
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
