import { useValues, useActions, useMountedLogic } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import {
    FunnelStepReference,
    StepOrderValue,
    EditorFilterProps,
    QueryEditorFilterProps,
    FunnelsFilterType,
} from '~/types'
import { FunnelStepOrderPicker } from '../views/Funnels/FunnelStepOrderPicker'
import { FunnelExclusionsFilter } from '../filters/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../filters/FunnelStepReferencePicker'
import { funnelCommandLogic } from '../views/Funnels/funnelCommandLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { PureField } from 'lib/forms/Field'
import { Noun } from '~/models/groupsModel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function FunnelsAdvancedDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter, aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    // TODO: Replicate command logic
    // useMountedLogic(funnelCommandLogic)

    return (
        <FunnelsAdvancedComponent
            aggregationTargetLabel={aggregationTargetLabel}
            // TODO: implement
            advancedOptionsUsedCount={0}
            setFilters={updateInsightFilter}
            {...insightFilter}
        />
    )
}

export function FunnelsAdvanced({ insightProps }: EditorFilterProps): JSX.Element {
    const { filters, aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    useMountedLogic(funnelCommandLogic)

    return (
        <FunnelsAdvancedComponent
            aggregationTargetLabel={aggregationTargetLabel}
            advancedOptionsUsedCount={advancedOptionsUsedCount}
            setFilters={setFilters}
            {...filters}
        />
    )
}

type FunnelsAdvancedComponentProps = {
    aggregationTargetLabel: Noun
    advancedOptionsUsedCount: number
    setFilters: (filters: Partial<FunnelsFilterType>) => void
} & FunnelsFilterType

export function FunnelsAdvancedComponent({
    aggregationTargetLabel,
    advancedOptionsUsedCount,
    aggregation_group_type_index,
    setFilters,
}: FunnelsAdvancedComponentProps): JSX.Element {
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
                        aggregation_group_type_index={aggregation_group_type_index}
                    />
                }
            >
                <FunnelExclusionsFilter />
            </PureField>

            {!!advancedOptionsUsedCount && (
                <div className="mt-4">
                    <LemonButton
                        status="danger"
                        onClick={() => {
                            // TODO: check that this works, try setting to undefined
                            // setStepReference(FunnelStepReference.total)
                            setFilters({
                                funnel_order_type: StepOrderValue.ORDERED,
                                funnel_step_reference: FunnelStepReference.total, // new - why not undefined?
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
