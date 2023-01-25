import { useValues, useActions, useMountedLogic } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { EditorFilterProps, QueryEditorFilterProps, FunnelsFilterType } from '~/types'
import { FunnelStepOrderPicker, FunnelStepOrderPickerDataExploration } from '../views/Funnels/FunnelStepOrderPicker'
import { FunnelExclusionsFilter } from '../filters/FunnelExclusionsFilter'
import {
    FunnelStepReferencePicker,
    FunnelStepReferencePickerDataExploration,
} from '../filters/FunnelStepReferencePicker'
import { funnelCommandLogic } from '../views/Funnels/funnelCommandLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { PureField } from 'lib/forms/Field'
import { Noun } from '~/models/groupsModel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function FunnelsAdvancedDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter, aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    // TODO: Replicate command logic
    // useMountedLogic(funnelCommandLogic)

    return (
        <FunnelsAdvancedComponent
            dataExploration={true}
            aggregationTargetLabel={aggregationTargetLabel}
            advancedOptionsUsedCount={advancedOptionsUsedCount}
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
            dataExploration={false}
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
    dataExploration: boolean
} & FunnelsFilterType

export function FunnelsAdvancedComponent({
    aggregationTargetLabel,
    advancedOptionsUsedCount,
    aggregation_group_type_index,
    setFilters,
    dataExploration,
}: FunnelsAdvancedComponentProps): JSX.Element {
    return (
        <div className="space-y-4">
            <PureField label="Step order" info={<StepOrderInfo />}>
                {dataExploration ? <FunnelStepOrderPickerDataExploration /> : <FunnelStepOrderPicker />}
            </PureField>
            <PureField label="Conversion rate calculation">
                {dataExploration ? <FunnelStepReferencePickerDataExploration /> : <FunnelStepReferencePicker />}
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
                            setFilters({
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
