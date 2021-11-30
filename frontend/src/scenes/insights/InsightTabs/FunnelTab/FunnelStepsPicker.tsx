import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { EntityFilter, FunnelVizType } from '~/types'
import { Row, Select } from 'antd'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelStepsPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters, numberOfSeries, areFiltersValid, filterSteps } = useValues(funnelLogic(insightProps))
    const { changeStepRange } = useActions(funnelLogic(insightProps))

    if (filters.funnel_viz_type === FunnelVizType.Steps) {
        return null
    }

    const onChange = (funnel_from_step?: number, funnel_to_step?: number): void => {
        changeStepRange(funnel_from_step, funnel_to_step)
    }

    const fromRange = areFiltersValid ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice(0, -1) : [0]
    const toRange = areFiltersValid
        ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice((filters.funnel_from_step ?? 0) + 1)
        : [1]

    const renderStepOptions = (range: number[]): React.ReactNode => {
        return range.map((stepIndex) => {
            const stepFilter = filterSteps.find((f) => f.order === stepIndex)

            return stepFilter ? (
                <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                    <div style={{ display: 'flex', flexDirection: 'row' }}>
                        Step {stepIndex + 1} (
                        <EntityFilterInfo filter={stepFilter as EntityFilter} showSubTitle={false} />)
                    </div>
                </Select.Option>
            ) : null
        })
    }

    return (
        <Row className="funnel-options-inputs">
            <span className="text-muted-alt">between</span>
            <Select
                defaultValue={0}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomLeft}
                data-attr="funnel-header-steps-funnel_from_step-selector"
                optionLabelProp="label"
                value={filters.funnel_from_step}
                onChange={(fromStep: number) => onChange(fromStep, filters.funnel_to_step)}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {renderStepOptions(fromRange)}
            </Select>
            <span className="text-muted-alt">to</span>
            <Select
                defaultValue={Math.max(numberOfSeries - 1, 1)}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomLeft}
                data-attr="funnel-header-steps-funnel_to_step-selector"
                optionLabelProp="label"
                value={filters.funnel_to_step}
                onChange={(toStep: number) => onChange(filters.funnel_from_step, toStep)}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {renderStepOptions(toRange)}
            </Select>
        </Row>
    )
}
