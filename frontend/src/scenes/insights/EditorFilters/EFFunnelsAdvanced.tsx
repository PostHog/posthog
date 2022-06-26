import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelStepReference, StepOrderValue, EditorFilterProps } from '~/types'
import { FunnelStepOrderPicker } from '../InsightTabs/FunnelTab/FunnelStepOrderPicker'
import { FunnelExclusionsFilter } from '../Filters/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../Filters/FunnelStepReferencePicker'
import { funnelCommandLogic } from '../InsightTabs/FunnelTab/funnelCommandLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { EditorFilterItemTitle } from './EditorFilterItemTitle'

export function EFFunnelsAdvanced({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))
    const { setFilters, setStepReference } = useActions(funnelLogic(insightProps))
    useMountedLogic(funnelCommandLogic)

    return (
        <div className="space-y">
            <EditorFilterItemTitle
                label="Step order"
                tooltip={
                    <ul style={{ paddingLeft: '1.2rem' }}>
                        <li>
                            <b>Sequential</b> - Step B must happen after Step A, but any number events can happen
                            between A and B.
                        </li>
                        <li>
                            <b>Strict Order</b> - Step B must happen directly after Step A without any events in
                            between.
                        </li>
                        <li>
                            <b>Any Order</b> - Steps can be completed in any sequence.
                        </li>
                    </ul>
                }
            />
            <FunnelStepOrderPicker />

            <EditorFilterItemTitle label="Conversion rate calculation" />
            <FunnelStepReferencePicker bordered />

            <EditorFilterItemTitle
                label="Exclusion steps"
                tooltip={
                    <>
                        Exclude {aggregationTargetLabel.plural}{' '}
                        {filters.aggregation_group_type_index != undefined ? 'that' : 'who'} completed the specified
                        event between two specific steps. Note that these {aggregationTargetLabel.plural} will be{' '}
                        <b>completely excluded from the entire funnel</b>.
                    </>
                }
            />
            <FunnelExclusionsFilter />

            {!!advancedOptionsUsedCount && (
                <div className="mt">
                    <LemonButton
                        type="stealth"
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
