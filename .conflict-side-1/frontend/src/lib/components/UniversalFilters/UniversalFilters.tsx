import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDropdown, Popover } from '@posthog/lemon-ui'

import { OperatorValueSelectProps } from 'lib/components/PropertyFilters/components/OperatorValueSelect'

import { AnyDataNode } from '~/queries/schema/schema-general'
import { UniversalFilterValue, UniversalFiltersGroup } from '~/types'

import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
import { isValidPropertyFilter } from '../PropertyFilters/utils'
import { TaxonomicFilter } from '../TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { UniversalFilterButton } from './UniversalFilterButton'
import { universalFiltersLogic } from './universalFiltersLogic'
import { isEditableFilter, isEventFilter } from './utils'

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
    metadataSource,
    className,
    operatorAllowlist,
}: {
    index: number
    filter: UniversalFilterValue
    onChange: (property: UniversalFilterValue) => void
    onRemove: () => void
    initiallyOpen?: boolean
    metadataSource?: AnyDataNode
    className?: string
    operatorAllowlist?: OperatorValueSelectProps['operatorAllowlist']
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
                        metadataSource={metadataSource}
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
                        operatorAllowlist={operatorAllowlist}
                    />
                ) : null
            }
        >
            <UniversalFilterButton
                onClick={() => setOpen(!open)}
                onClose={onRemove}
                filter={filter}
                className={className}
            />
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
                    onChange={(taxonomicGroup, value, item, originalQuery) => {
                        addGroupFilter(taxonomicGroup, value, item, originalQuery)
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
                {props?.title || 'Add filter'}
            </LemonButton>
        </LemonDropdown>
    )
}

const PureTaxonomicFilter = ({
    fullWidth = true,
    onChange,
}: {
    fullWidth?: boolean
    onChange: () => void
}): JSX.Element => {
    const { taxonomicGroupTypes } = useValues(universalFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    return (
        <TaxonomicFilter
            {...(fullWidth ? { width: '100%' } : {})}
            onChange={(taxonomicGroup, value, item, originalQuery) => {
                onChange()
                addGroupFilter(taxonomicGroup, value, item, originalQuery)
            }}
            taxonomicGroupTypes={taxonomicGroupTypes}
        />
    )
}

UniversalFilters.Group = Group
UniversalFilters.Value = Value
UniversalFilters.AddFilterButton = AddFilterButton
UniversalFilters.PureTaxonomicFilter = PureTaxonomicFilter

export default UniversalFilters
