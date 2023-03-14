import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { EntityFilter } from '~/types'
import { Select } from 'antd'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelStepsPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters, numberOfSeries, isFunnelWithEnoughSteps, filterSteps } = useValues(funnelLogic(insightProps))
    const { changeStepRange } = useActions(funnelLogic(insightProps))

    const onChange = (funnel_from_step?: number, funnel_to_step?: number): void => {
        changeStepRange(funnel_from_step, funnel_to_step)
    }

    const fromRange = isFunnelWithEnoughSteps ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice(0, -1) : [0]
    const toRange = isFunnelWithEnoughSteps
        ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice((filters.funnel_from_step ?? 0) + 1)
        : [1]

    const renderStepOptions = (range: number[]): React.ReactNode => {
        return range.map((stepIndex) => {
            const stepFilter = filterSteps.find((f) => f.order === stepIndex)

            return stepFilter ? (
                <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                    <div className="flex flex-row">
                        <span className="mr-1">Step {stepIndex + 1}:</span>
                        <EntityFilterInfo filter={stepFilter as EntityFilter} />
                    </div>
                </Select.Option>
            ) : null
        })
    }

    return (
        <div className="flex items-center">
            <span className="text-muted-alt">&nbsp;from</span>
            <Select
                disabled={!isFunnelWithEnoughSteps}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomLeft}
                data-attr="funnel-header-steps-funnel_from_step-selector"
                optionLabelProp="label"
                value={filters.funnel_from_step || 0}
                onChange={(fromStep: number) => onChange(fromStep, filters.funnel_to_step)}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {renderStepOptions(fromRange)}
            </Select>
            <span className="text-muted-alt">to</span>
            <Select
                disabled={!isFunnelWithEnoughSteps}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomLeft}
                data-attr="funnel-header-steps-funnel_to_step-selector"
                optionLabelProp="label"
                value={filters.funnel_to_step || Math.max(numberOfSeries - 1, 1)}
                onChange={(toStep: number) => onChange(filters.funnel_from_step, toStep)}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {renderStepOptions(toRange)}
            </Select>
        </div>
    )
}
