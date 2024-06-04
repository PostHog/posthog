import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown, Popover } from '@posthog/lemon-ui'
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
    taxonomicEntityFilterGroupTypes: TaxonomicFilterGroupType[]
    taxonomicPropertyFilterGroupTypes: TaxonomicFilterGroupType[]
    children?: React.ReactNode
}

function UniversalFilters({
    rootKey,
    group = null,
    onChange,
    taxonomicEntityFilterGroupTypes,
    taxonomicPropertyFilterGroupTypes,
    children,
}: UniversalFiltersProps): JSX.Element {
    return (
        <BindLogic
            logic={universalFiltersLogic}
            props={{
                rootKey,
                group,
                onChange,
                taxonomicEntityFilterGroupTypes,
                taxonomicPropertyFilterGroupTypes,
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
    const { rootKey, taxonomicEntityFilterGroupTypes, taxonomicPropertyFilterGroupTypes } =
        useValues(universalFiltersLogic)
    const { replaceGroupValue } = useActions(universalFiltersLogic)

    return (
        <UniversalFilters
            key={index}
            rootKey={`${rootKey}.group_${index}`}
            group={group}
            onChange={(group) => replaceGroupValue(index, group)}
            taxonomicEntityFilterGroupTypes={taxonomicEntityFilterGroupTypes}
            taxonomicPropertyFilterGroupTypes={taxonomicPropertyFilterGroupTypes}
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
}: {
    index: number
    filter: UniversalFilterValue
    onChange: (property: UniversalFilterValue) => void
    onRemove: () => void
}): JSX.Element => {
    const { rootKey, taxonomicPropertyFilterGroupTypes } = useValues(universalFiltersLogic)

    const isEvent = isEventFilter(filter)
    const isEditable = isEditableFilter(filter)

    const [open, setOpen] = useState<boolean>(isEditable)

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

const AddFilterButton = (): JSX.Element => {
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
                type="secondary"
                size="small"
                icon={<IconPlusSmall />}
                sideIcon={null}
                onClick={() => setDropdownOpen(!dropdownOpen)}
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
