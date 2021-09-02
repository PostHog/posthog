import React, { useState } from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { groupsLogic } from '../../../groups/groupsLogic'

enum UniquenessBasis {
    Person = 'person',
    Group = 'group',
}

interface UniquenessBasisOption {
    label: string
    value: UniquenessBasis
}

const uniquenessBasisOptions: UniquenessBasisOption[] = [
    {
        label: 'Persons',
        value: UniquenessBasis.Person,
    },
    {
        label: 'Groups of type',
        value: UniquenessBasis.Group,
    },
]

export function UniquenessBasisPicker(): JSX.Element {
    const { filters } = useValues(funnelLogic)
    const { setFilters } = useActions(funnelLogic)
    const { groupTypes } = useValues(groupsLogic)
    const [uniquenessBasis, setUniquenessBasis] = useState<UniquenessBasis>(
        filters.unique_group_type_id ? UniquenessBasis.Group : UniquenessBasis.Person
    )

    return (
        <div style={{ display: 'flex' }}>
            <Select
                id="funnel-uniqueness-basis-picker"
                data-attr="funnel-uniqueness-basis-picker"
                value={uniquenessBasis}
                onSelect={(newValue) => {
                    setUniquenessBasis(newValue)
                    if (newValue !== UniquenessBasis.Group) {
                        setFilters({ unique_group_type_id: undefined })
                    }
                }}
                listHeight={440}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                optionLabelProp="label"
                options={uniquenessBasisOptions}
            />
            {uniquenessBasis === UniquenessBasis.Group && (
                <Select
                    id="funnel-uniqueness-basis-group-type-picker"
                    data-attr="funnel-uniqueness-basis-group-type-picker"
                    value={filters.unique_group_type_id}
                    placeholder="Select group type"
                    onSelect={(groupTypeId) => setFilters({ unique_group_type_id: groupTypeId })}
                    listHeight={440}
                    dropdownMatchSelectWidth={false}
                    dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                    optionLabelProp="label"
                    options={groupTypes.map(({ type_key, type_id }) => ({ label: type_key, value: type_id }))}
                    style={{ marginLeft: '0.5rem' }}
                />
            )}
        </div>
    )
}
