import { LemonButton } from '@posthog/lemon-ui'
import { Select } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconDelete } from 'lib/lemon-ui/icons'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { getClampedStepRangeFilterDataExploration } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { FunnelsQuery } from '~/queries/schema'
import { ActionFilter as ActionFilterType, FunnelExclusion, FunnelsFilterType } from '~/types'

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
    const { querySource, insightFilter, series, isFunnelWithEnoughSteps, exclusionDefaultStepRange } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

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
        <div className={clsx('flex items-center flex-nowrap pl-1 mx-0', isVertical ? 'w-full my-1' : 'w-auto my-0')}>
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
        </div>
    )
}
