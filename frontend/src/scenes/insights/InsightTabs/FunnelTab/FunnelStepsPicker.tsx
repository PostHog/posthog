import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelVizType } from '~/types'
import { Row, Select } from 'antd'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'

export function FunnelStepsPicker(): JSX.Element | null {
    const { filters, numberOfSeries, areFiltersValid } = useValues(funnelLogic)
    const { changeHistogramStep } = useActions(funnelLogic)

    if (filters.funnel_viz_type === FunnelVizType.Steps) {
        return null
    }

    const onChange = (funnel_from_step?: number, funnel_to_step?: number): void => {
        changeHistogramStep(funnel_from_step, funnel_to_step)
    }

    return (
        <Row align="middle" style={{ margin: '8px 0' }}>
            Between
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
                {Array.from(Array(numberOfSeries).keys())
                    .slice(0, -1)
                    .map((stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>
            and
            <Select
                defaultValue={numberOfSeries - 1}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-header-steps-funnel_to_step-selector"
                optionLabelProp="label"
                value={filters.funnel_to_step}
                onChange={(toStep: number) => onChange(undefined, toStep)}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {Array.from(Array(numberOfSeries).keys())
                    .slice((filters.funnel_from_step ?? 0) + 1)
                    .map((stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>
        </Row>
    )
}
