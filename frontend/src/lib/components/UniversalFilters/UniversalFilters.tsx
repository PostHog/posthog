import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDropdown, Popover } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from '../PropertyFilters/utils'
import { TaxonomicFilter } from '../TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { UniversalFilterButton } from './UniversalFilterButton'
import { universalFiltersLogic } from './universalFiltersLogic'
import { isEditableFilter, isEventFilter } from './utils'

export interface UniversalFiltersGroup {
    type: FilterLogicalOperator
    values: UniversalFiltersGroupValue[]
}

export type UniversalFiltersGroupValue = UniversalFiltersGroup | UniversalFilterValue
export type UniversalFilterValue = AnyPropertyFilter | ActionFilter

type UniversalFiltersProps = {
    rootKey: string
    group: UniversalFiltersGroup | null
    onChange: (group: UniversalFiltersGroup) => void
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    children?: React.ReactNode
}

function UniversalFilters({
    rootKey,
    group = null,
    onChange,
    taxonomicGroupTypes,
    children,
}: UniversalFiltersProps): JSX.Element {
    return (
        <BindLogic
            logic={universalFiltersLogic}
            props={{
                rootKey,
                group,
                onChange,
                taxonomicGroupTypes,
            }}
        >
            {children}
        </BindLogic>
    )
}

function Group({
    group,
    index,
    children,
}: {
    group: UniversalFiltersGroup
    index: number
    children: React.ReactNode
}): JSX.Element {
    const { rootKey, taxonomicGroupTypes } = useValues(universalFiltersLogic)
    const { replaceGroupValue } = useActions(universalFiltersLogic)

    return (
        <UniversalFilters
            key={index}
            rootKey={`${rootKey}.group_${index}`}
            group={group}
            onChange={(group) => replaceGroupValue(index, group)}
            taxonomicGroupTypes={taxonomicGroupTypes}
        >
            {children}
        </UniversalFilters>
    )
}

const Value = ({
    index,
    filter,
    onChange,
    onRemove,
    initiallyOpen = false,
}: {
    index: number
    filter: UniversalFilterValue
    onChange: (property: UniversalFilterValue) => void
    onRemove: () => void
    initiallyOpen?: boolean
}): JSX.Element => {
    const { rootKey, taxonomicPropertyFilterGroupTypes } = useValues(universalFiltersLogic)

    const isEvent = isEventFilter(filter)
    const isEditable = isEditableFilter(filter)

    const [open, setOpen] = useState<boolean>(isEditable && initiallyOpen)

    const pageKey = `${rootKey}.filter_${index}`

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                isEvent ? (
                    <PropertyFilters
                        pageKey={pageKey}
                        propertyFilters={filter.properties}
                        onChange={(properties) => onChange({ ...filter, properties })}
                        disablePopover
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    />
                ) : isEditable ? (
                    <TaxonomicPropertyFilter
                        pageKey={pageKey}
                        index={0}
                        filters={[filter]}
                        onComplete={() => {
                            if (isValidPropertyFilter(filter) && !filter.key) {
                                onRemove()
                            }
                        }}
                        setFilter={(_, property) => onChange(property)}
                        disablePopover={false}
                        taxonomicGroupTypes={taxonomicPropertyFilterGroupTypes}
                    />
                ) : null
            }
        >
            <UniversalFilterButton onClick={() => setOpen(!open)} onClose={onRemove} filter={filter} />
        </Popover>
    )
}

const AddFilterButton = (props: Omit<LemonButtonProps, 'onClick' | 'sideAction' | 'icon'>): JSX.Element => {
    const [dropdownOpen, setDropdownOpen] = useState<boolean>(false)

    const { taxonomicGroupTypes } = useValues(universalFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    return (
        <LemonDropdown
            overlay={
                <TaxonomicFilter
                    onChange={(taxonomicGroup, value, item) => {
                        addGroupFilter(taxonomicGroup, value, item)
                        setDropdownOpen(false)
                    }}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                />
            }
            visible={dropdownOpen}
            onClickOutside={() => setDropdownOpen(false)}
        >
            <LemonButton
                icon={<IconPlusSmall />}
                sideIcon={null}
                onClick={() => setDropdownOpen(!dropdownOpen)}
                {...props}
            >
                Add filter
            </LemonButton>
        </LemonDropdown>
    )
}

UniversalFilters.Group = Group
UniversalFilters.Value = Value
UniversalFilters.AddFilterButton = AddFilterButton

export default UniversalFilters
