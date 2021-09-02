import React from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ANTD_TOOLTIP_PLACEMENTS, capitalizeFirstLetter, pluralize } from 'lib/utils'
import { groupsLogic } from '../../../groups/groupsLogic'

interface UniquenessBasisOption {
    label: string
    value: number
}

export function UniquenessBasisPicker(): JSX.Element {
    const { filters } = useValues(funnelLogic)
    const { setFilters } = useActions(funnelLogic)
    const { groupTypes } = useValues(groupsLogic)

    const uniquenessBasisOptions: UniquenessBasisOption[] = [
        {
            label: 'Persons',
            value: -1,
        },
        ...groupTypes.map(({ type_key, type_id }) => ({
            label: capitalizeFirstLetter(pluralize(2, type_key, undefined, false)),
            value: type_id,
        })),
    ]

    return (
        <div style={{ display: 'flex' }}>
            <Select
                id="funnel-uniqueness-basis-picker"
                data-attr="funnel-uniqueness-basis-picker"
                value={filters.unique_group_type_id ?? -1}
                onSelect={(newValue) => {
                    setFilters({ unique_group_type_id: newValue >= 0 ? newValue : undefined })
                }}
                listHeight={440}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomLeft}
                optionLabelProp="label"
                options={uniquenessBasisOptions}
            />
        </div>
    )
}
