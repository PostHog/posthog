import { Select } from 'antd'
import Fuse from 'fuse.js'
import { useActions } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'

import { SelectOption } from '~/types'

interface Props {
    optionGroups: Array<PropertyOptionGroup>
    value: Partial<SelectOption> | null
    onChange: (type: PropertyOptionGroup['type'], value: string) => void
    placeholder: string
    autoOpenIfEmpty?: boolean
    delayBeforeAutoOpen?: number
    dropdownMatchSelectWidth?: boolean | number
}

export interface PropertyOptionGroup {
    type: 'event' | 'person' | 'element'
    label: string
    options: Array<{ value: string }>
}

interface SelectionOptionType {
    key: string
    value: string
    type: 'event' | 'person' | 'element'
}

const fuseCache: Record<string, any> = {}

export const searchItems = (
    sources: Array<{ value: string }>,
    search: string | false,
    groupType: 'event' | 'person' | 'element'
): Array<{ value: string }> => {
    if (!search) {
        return sources
    }

    if (!fuseCache[groupType]) {
        fuseCache[groupType] = new Fuse(sources, {
            keys: ['value'],
            threshold: 0.3,
        })
    }
    return fuseCache[groupType].search(search).map((result: Record<string, { item: string }>) => {
        return result.item
    })
}

export function PropertySelect({
    optionGroups,
    value: propertyOption,
    onChange,
    placeholder,
    autoOpenIfEmpty,
    delayBeforeAutoOpen,
    dropdownMatchSelectWidth = true,
}: Props): JSX.Element {
    const [search, setSearch] = useState(false as string | false)
    const { reportPropertySelectOpened } = useActions(eventUsageLogic)
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
            onSearch={(value) => {
                setSearch(value)
            }}
            filterOption={() => {
                return true // set to avoid ant.d doing its own filtering
            }}
            onChange={(_: null, selection) => {
                const { value: val, type } = selection as unknown as SelectionOptionType
                onChange(type, val.replace(/^(event_|person_|element_)/gi, ''))
            }}
            style={{ width: '100%' }}
            dropdownMatchSelectWidth={dropdownMatchSelectWidth}
            onDropdownVisibleChange={(open) => {
                if (open) {
                    reportPropertySelectOpened()
                }
            }}
        >
            {optionGroups.map(
                (group) =>
                    group.options?.length > 0 && (
                        <Select.OptGroup key={group.type} label={group.label}>
                            {searchItems(group.options, search, group.type).map((option, index) => (
                                <Select.Option
                                    key={`${group.type}_${option.value}`}
                                    value={`${group.type}_${option.value}`}
                                    type={group.type}
                                    data-attr={`prop-filter-${group.type}-${index}`}
                                >
                                    <PropertyKeyInfo
                                        value={option.value}
                                        type={
                                            group.type === 'element'
                                                ? TaxonomicFilterGroupType.Elements
                                                : group.type === 'person'
                                                ? TaxonomicFilterGroupType.PersonProperties
                                                : TaxonomicFilterGroupType.EventProperties
                                        }
                                    />
                                </Select.Option>
                            ))}
                        </Select.OptGroup>
                    )
            )}
        </SelectGradientOverflow>
    )
}
