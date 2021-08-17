import React from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'

export function FunnelExclusionsFilter(): JSX.Element {
    const { exclusionFilters } = useValues(funnelLogic)
    const { setEventExclusionFilters } = useActions(funnelLogic)

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
            customRowSuffix={(filter) => {
                console.log('ROW', filter)
                return (
                    <>
                        between{' '}
                        <Select
                            defaultValue={1}
                            dropdownMatchSelectWidth={false}
                            dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                            data-attr="funnel-exclusion-funnel_from_step-selector"
                            optionLabelProp="label"
                        >
                            <Select.Option value={1} label={'Step 1'}>
                                Step 1
                            </Select.Option>
                            <Select.Option value={2} label={'Step 2'}>
                                Step 2
                            </Select.Option>
                        </Select>{' '}
                        and{' '}
                        <Select
                            defaultValue={2}
                            dropdownMatchSelectWidth={false}
                            dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                            data-attr="funnel-exclusion-funnel_to_step-selector"
                            optionLabelProp="label"
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
            }}
        />
    )
}
