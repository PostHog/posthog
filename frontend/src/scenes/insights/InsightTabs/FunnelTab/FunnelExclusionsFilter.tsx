import React, { useState } from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { FunnelExclusionEntityFilter } from '~/types'

function ExclusionRowSuffix({ filter, index }: { filter: FunnelExclusionEntityFilter; index: number }): JSX.Element {
    const { stepsWithCount } = useValues(funnelLogic)
    const { setOneEventExclusionFilter } = useActions(funnelLogic)
    const [stepRange, setStepRange] = useState<Partial<FunnelExclusionEntityFilter>>({
        funnel_from_step: 0,
        funnel_to_step: stepsWithCount.length - 1,
    })

    const setExclusionRowValue = (): void => {
        setOneEventExclusionFilter({ ...filter, ...stepRange }, index)
    }

    const onBlur = (): void => {
        if (
            stepRange.funnel_from_step !== stepRange.funnel_from_step ||
            stepRange.funnel_to_step !== stepRange.funnel_to_step
        ) {
            setExclusionRowValue()
        }
    }

    return (
        <>
            between{' '}
            <Select
                defaultValue={0}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_from_step-selector"
                optionLabelProp="label"
                value={stepRange.funnel_from_step}
                onChange={(funnel_from_step: number) => setStepRange((state) => ({ ...state, funnel_from_step }))}
                onBlur={onBlur}
            >
                {stepsWithCount &&
                    stepsWithCount.map((_, stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>{' '}
            and{' '}
            <Select
                defaultValue={stepsWithCount.length - 1}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_to_step-selector"
                optionLabelProp="label"
                value={stepRange.funnel_to_step}
                onChange={(funnel_to_step: number) => setStepRange((state) => ({ ...state, funnel_to_step }))}
                onBlur={onBlur}
            >
                <Select.Option value={2} label={'Step 2'}>
                    Step 2
                </Select.Option>
                <Select.Option value={3} label={'Step 3'}>
                    Step 3
                </Select.Option>
            </Select>
        </>
    )
}

export function FunnelExclusionsFilter(): JSX.Element | null {
    const { exclusionFilters, areFiltersValid } = useValues(funnelLogic)
    const { setEventExclusionFilters } = useActions(funnelLogic)

    if (!areFiltersValid) {
        return null
    }

    console.log('EXCLUSION FILTERS', exclusionFilters)

    return (
        <ActionFilter
            setFilters={setEventExclusionFilters}
            filters={exclusionFilters}
            typeKey="funnel-exclusions-filter"
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
