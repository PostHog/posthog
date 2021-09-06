import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelVizType } from '~/types'
import { Row, Select } from 'antd'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'

export function FunnelStepsPicker(): JSX.Element | null {
    const { filters, numberOfSeries, areFiltersValid } = useValues(funnelLogic)
    const { changeStepRange } = useActions(funnelLogic)

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

    return (
        <Row className="funnel-options-inputs">
            <span className="text-muted-alt">between</span>
            <Select
                defaultValue={0}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-header-steps-funnel_from_step-selector"
                optionLabelProp="label"
                value={filters.funnel_from_step}
                onChange={(fromStep: number) => onChange(fromStep)}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {fromRange.map((stepIndex) => (
                    <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                        Step {stepIndex + 1}
                    </Select.Option>
                ))}
            </Select>
            <span className="text-muted-alt">to</span>
            <Select
                defaultValue={Math.max(numberOfSeries - 1, 1)}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-header-steps-funnel_to_step-selector"
                optionLabelProp="label"
                value={filters.funnel_to_step}
                onChange={(toStep: number) => onChange(undefined, toStep)}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {toRange.map((stepIndex) => (
                    <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                        Step {stepIndex + 1}
                    </Select.Option>
                ))}
            </Select>
        </Row>
    )
}
