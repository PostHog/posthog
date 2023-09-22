import { Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { FunnelExclusion, ActionFilter as ActionFilterType, FunnelsFilterType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconDelete } from 'lib/lemon-ui/icons'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { FunnelsQuery } from '~/queries/schema'
import { getClampedStepRangeFilterDataExploration } from 'scenes/funnels/funnelUtils'

type ExclusionRowSuffixComponentBaseProps = {
    filter: ActionFilterType | FunnelExclusion
    index: number
    onClose?: () => void
    isVertical: boolean
}

export function ExclusionRowSuffix({
    filter,
    index,
    onClose,
    isVertical,
}: ExclusionRowSuffixComponentBaseProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, insightFilter, exclusionDefaultStepRange, isFunnelWithEnoughSteps, series } = useValues(
        funnelDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const setOneEventExclusionFilter = (eventFilter: FunnelExclusion, index: number): void => {
        const exclusions = ((insightFilter as FunnelsFilterType)?.exclusions || []).map((e, e_i) =>
            e_i === index
                ? getClampedStepRangeFilterDataExploration({
                      stepRange: eventFilter,
                      query: querySource as FunnelsQuery,
                  })
                : e
        )

        updateInsightFilter({
            exclusions,
        })
    }

    const exclusions = (insightFilter as FunnelsFilterType)?.exclusions
    const numberOfSeries = series?.length || 0

    const stepRange = {
        funnel_from_step: exclusions?.[index]?.funnel_from_step ?? exclusionDefaultStepRange.funnel_from_step,
        funnel_to_step: exclusions?.[index]?.funnel_to_step ?? exclusionDefaultStepRange.funnel_to_step,
    }

    const onChange = (
        funnel_from_step: number | undefined = stepRange.funnel_from_step,
        funnel_to_step: number | undefined = stepRange.funnel_to_step
    ): void => {
        setOneEventExclusionFilter(
            {
                ...filter,
                funnel_from_step,
                funnel_to_step,
            },
            index
        )
    }

    return (
        <Row
            align="middle"
            wrap={false}
            style={{ margin: `${isVertical ? 4 : 0}px 0`, paddingLeft: 4, width: isVertical ? '100%' : 'auto' }}
        >
            between
            <Select
                defaultValue={0}
                disabled={!isFunnelWithEnoughSteps}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_from_step-selector"
                optionLabelProp="label"
                value={stepRange.funnel_from_step}
                onChange={(fromStep: number) => onChange(fromStep)}
                onBlur={() => onChange}
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
                defaultValue={(stepRange.funnel_from_step ?? 0) + 1}
                disabled={!isFunnelWithEnoughSteps}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_to_step-selector"
                optionLabelProp="label"
                value={stepRange.funnel_to_step}
                onChange={(toStep: number) => onChange(stepRange.funnel_from_step, toStep)}
                onBlur={() => onChange}
                style={{ marginLeft: 4 }}
            >
                {Array.from(Array(numberOfSeries).keys())
                    .slice((stepRange.funnel_from_step ?? 0) + 1)
                    .map((stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>
            <LemonButton
                icon={<IconDelete />}
                status="primary-alt"
                onClick={onClose}
                data-attr="delete-prop-exclusion-filter"
                title="Delete event exclusion series"
            />
        </Row>
    )
}
