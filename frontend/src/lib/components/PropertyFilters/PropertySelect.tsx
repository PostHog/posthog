import React from 'react'
import { Select } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { EventProperty } from 'scenes/teamLogic'

type PropertyOption = EventProperty

interface Props {
    optionGroups: Array<PropertyOptionGroup>
    value: Partial<PropertyOption> | null
    onChange: (type: PropertyOptionGroup['type'], value: string) => void
    placeholder: string
    autoOpenIfEmpty?: boolean
    delayBeforeAutoOpen?: number | false
}

interface PropertyOptionGroup {
    type: 'event' | 'person' | 'element'
    label: string
    options: Array<{ value: string }>
}

interface SelectionOptionType {
    key: string
    value: string
    type: 'event' | 'person' | 'element'
}

export function PropertySelect({
    optionGroups,
    value: propertyOption,
    onChange,
    placeholder,
    autoOpenIfEmpty,
    delayBeforeAutoOpen,
}: Props): JSX.Element {
    return (
        <SelectGradientOverflow
            showSearch
            autoFocus={autoOpenIfEmpty && !propertyOption?.value}
            defaultOpen={autoOpenIfEmpty && !propertyOption?.value}
            delayBeforeAutoOpen={delayBeforeAutoOpen}
            placeholder={placeholder}
            data-attr="property-filter-dropdown"
            labelInValue
            value={propertyOption || undefined}
            filterOption={(input, option) => option?.value?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
            onChange={(_: null, selection) => {
                const { value: val, type } = selection as SelectionOptionType
                onChange(type, val.replace(/^(event_|person_|element_)/gi, ''))
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
