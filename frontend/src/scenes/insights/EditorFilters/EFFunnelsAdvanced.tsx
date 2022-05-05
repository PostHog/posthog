import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'
import clsx from 'clsx'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Button, Tag } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { FunnelStepReference, StepOrderValue, EditorFilterProps } from '~/types'
import { IconArrowDropDown } from 'lib/components/icons'
import { FunnelStepOrderPicker } from '../InsightTabs/FunnelTab/FunnelStepOrderPicker'
import { FunnelExclusionsFilter } from '../InsightTabs/FunnelTab/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { funnelCommandLogic } from '../InsightTabs/FunnelTab/funnelCommandLogic'

export function EFFunnelsAdvanced({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))
    const { setFilters, toggleAdvancedMode, setStepReference } = useActions(funnelLogic(insightProps))
    useMountedLogic(funnelCommandLogic)

    return (
        <>
            <hr />
            <div className="flex-center cursor-pointer" onClick={toggleAdvancedMode}>
                <h4 className="secondary" style={{ flexGrow: 1 }}>
                    Advanced options{' '}
                    {!filters.funnel_advanced && !!advancedOptionsUsedCount && (
                        <Tag className="lemonade-tag">{advancedOptionsUsedCount}</Tag>
                    )}
                </h4>
                <div>
                    <div className={clsx('advanced-options-dropdown', filters.funnel_advanced && 'expanded')}>
                        <IconArrowDropDown />
                    </div>
                </div>
            </div>
            {filters.funnel_advanced ? (
                <div className="funnel-advanced-options">
                    <div className="mb-05">
                        Step order
                        <Tooltip
                            title={
                                <ul style={{ paddingLeft: '1.2rem' }}>
                                    <li>
                                        <b>Sequential</b> - Step B must happen after Step A, but any number events can
                                        happen between A and B.
                                    </li>
                                    <li>
                                        <b>Strict Order</b> - Step B must happen directly after Step A without any
                                        events in between.
                                    </li>
                                    <li>
                                        <b>Any Order</b> - Steps can be completed in any sequence.
                                    </li>
                                </ul>
                            }
                        >
                            <InfoCircleOutlined className="info-indicator" style={{ marginRight: 4 }} />
                        </Tooltip>
                    </div>
                    <FunnelStepOrderPicker />
                    <div className="mt">Conversion rate calculation</div>
                    <FunnelStepReferencePicker bordered />
                    <div className="mt">
                        Exclusion steps
                        <Tooltip
                            title={
                                <>
                                    Exclude {aggregationTargetLabel.plural}{' '}
                                    {filters.aggregation_group_type_index != undefined ? 'that' : 'who'} completed the
                                    specified event between two specific steps. Note that these{' '}
                                    {aggregationTargetLabel.plural} will be{' '}
                                    <b>completely excluded from the entire funnel</b>.
                                </>
                            }
                        >
                            <InfoCircleOutlined className="info-indicator" />
                        </Tooltip>
                    </div>
                    <div className="funnel-exclusions-filter">
                        <FunnelExclusionsFilter />
                    </div>
                    {!!advancedOptionsUsedCount && (
                        <div>
                            <Button
                                type="link"
                                style={{ color: 'var(--danger)', paddingLeft: 0, marginTop: 16 }}
                                onClick={() => {
                                    setStepReference(FunnelStepReference.total)
                                    setFilters({
                                        funnel_order_type: StepOrderValue.ORDERED,
                                        exclusions: [],
                                    })
                                }}
                            >
                                Reset advanced options
                            </Button>
                        </div>
                    )}
                </div>
            ) : (
                <div className="text-muted-alt cursor-pointer" onClick={toggleAdvancedMode}>
                    Exclude events between steps, custom conversion limit window and allow any step ordering.
                </div>
            )}
        </>
    )
}
