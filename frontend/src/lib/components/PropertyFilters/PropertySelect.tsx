import React from 'react'
import { Select } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { EventProperty } from 'scenes/userLogic'

type PropertyOption = EventProperty

interface Props {
    optionGroups: Array<PropertyOptionGroup>
    value: PropertyOption | null
    onChange: (type: PropertyOptionGroup['type'], value: string) => void
    placeholder: string
    autoOpenIfEmpty?: boolean
}

interface PropertyOptionGroup {
    type: 'event' | 'person' | 'element'
    label: string
    options: Array<{ value: string }>
}

export function PropertySelect({ optionGroups, value, onChange, placeholder, autoOpenIfEmpty }: Props): JSX.Element {
    return (
        <SelectGradientOverflow
            className={rrwebBlockClass}
            showSearch
            autoFocus={autoOpenIfEmpty && !value}
            defaultOpen={autoOpenIfEmpty && !value}
            placeholder={placeholder}
            data-attr="property-filter-dropdown"
            labelInValue
            value={value || undefined}
            filterOption={(input, option) => option?.value?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
            onChange={(_, { value, type }) => {
                onChange(type, value.replace(/^(event_|person_|element_)/gi, ''))
            }}
            style={{ width: '100%' }}
            virtual={false}
        >
            {optionGroups.map(
                (group) =>
                    group.options?.length > 0 && (
                        <Select.OptGroup key={group.type} label={group.label}>
                            {group.options.map((option, index) => (
                                <Select.Option
                                    key={`${group.type}_${option.value}`}
                                    value={`${group.type}_${option.value}`}
                                    type={group.type}
                                    data-attr={`prop-filter-${group.type}-${index}`}
                                >
                                    <PropertyKeyInfo
                                        value={option.value}
                                        type={group.type == 'element' ? group.type : undefined}
                                    />
                                </Select.Option>
                            ))}
                        </Select.OptGroup>
                    )
            )}
        </SelectGradientOverflow>
    )
}
