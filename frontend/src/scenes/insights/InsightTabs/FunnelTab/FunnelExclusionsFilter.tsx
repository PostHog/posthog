import React, { useState } from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { FunnelExclusionEntityFilter, ActionFilter as ActionFilterType } from '~/types'
import equal from 'fast-deep-equal'

function ExclusionRowSuffix({
    filter,
    index,
}: {
    filter: ActionFilterType | FunnelExclusionEntityFilter
    index: number
}): JSX.Element | null {
    const { exclusionFilters, exclusionDefaultStepRange, areFiltersValid, numberOfSeries } = useValues(funnelLogic)
    const { setOneEventExclusionFilter } = useActions(funnelLogic)

    if (!exclusionFilters.events?.[index]) {
        return null
    }

    const rowState = {
        funnel_from_step: exclusionFilters.events[index].funnel_from_step ?? exclusionDefaultStepRange.funnel_from_step,
        funnel_to_step: exclusionFilters.events[index].funnel_to_step ?? exclusionDefaultStepRange.funnel_to_step,
    }
    const [localStepRange, setLocalStepRange] = useState<Omit<FunnelExclusionEntityFilter, 'id' | 'name'>>(rowState)

    const setExclusionRowValue = (): void => {
        setOneEventExclusionFilter({ ...filter, ...localStepRange }, index)
    }

    const onBlur = (): void => {
        if (!equal(rowState, localStepRange)) {
            setExclusionRowValue()
        }
    }

    // const onChange = (fromStep: number): void => {
    //     const funnel_from_step = clamp(rowState.funnel_from_step, 0, exclusionDefaultStepRange.funnel_to_step - 1)
    //     setLocalStepRange({
    //         funnel_from_step,
    //         funnel_to_step: clamp(rowState.funnel_to_step, funnel_from_step + 1, exclusionDefaultStepRange.funnel_to_step),
    //     })
    // }

    // useEffect(() => {
    //
    // }, [exclusionDefaultStepRange])

    console.log('STEPS', localStepRange)
    console.log('BEFORE', Array.from(Array(numberOfSeries).keys()).slice(0, -1))
    console.log('AFTER', Array.from(Array(numberOfSeries).keys()).slice(localStepRange.funnel_from_step + 1))

    return (
        <>
            between{' '}
            <Select
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_from_step-selector"
                optionLabelProp="label"
                value={localStepRange.funnel_from_step}
                onChange={(funnel_from_step: number) => setLocalStepRange((state) => ({ ...state, funnel_from_step }))}
                onBlur={onBlur}
            >
                {Array.from(Array(numberOfSeries).keys())
                    .slice(0, -1)
                    .map((stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>{' '}
            and{' '}
            <Select
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_to_step-selector"
                optionLabelProp="label"
                value={localStepRange.funnel_to_step}
                onChange={(funnel_to_step: number) => setLocalStepRange((state) => ({ ...state, funnel_to_step }))}
                onBlur={onBlur}
            >
                {Array.from(Array(numberOfSeries).keys())
                    .slice(localStepRange.funnel_from_step + 1)
                    .map((stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>
        </>
    )
}

export function FunnelExclusionsFilter(): JSX.Element | null {
    const { exclusionFilters, areFiltersValid, exclusionDefaultStepRange } = useValues(funnelLogic)
    const { setEventExclusionFilters } = useActions(funnelLogic)

    console.log('EXCLUSION FILTERS', exclusionFilters)

    return (
        <ActionFilter
            setFilters={setEventExclusionFilters}
            filters={exclusionFilters}
            typeKey="funnel-exclusions-filter"
            addFilterDefaultOptions={exclusionDefaultStepRange}
            disabled={!areFiltersValid}
            buttonCopy="Add exclusion"
            groupTypes={[exclusionFilters.type as TaxonomicFilterGroupType]}
            hideMathSelector
            hidePropertySelector
            hideFilter
            fullWidth
            customRowSuffix={(filter, index) => <ExclusionRowSuffix filter={filter} index={index} />}
        />
    )
}
