import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDivider, LemonDropdown, Popover } from '@posthog/lemon-ui'

import { OperatorValueSelectProps } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { taxonomicFilterGroupTypeToEntityType } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { AnyDataNode } from '~/queries/schema/schema-general'
import { EntityTypes, UniversalFilterValue, UniversalFiltersGroup } from '~/types'

import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from '../PropertyFilters/utils'
import { TaxonomicFilter } from '../TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
    isQuickFilterItem,
    quickFilterToPropertyFilters,
} from '../TaxonomicFilter/types'
import { UniversalFilterButton } from './UniversalFilterButton'
import { universalFiltersLogic } from './universalFiltersLogic'
import { isEditableFilter, isEventFilter } from './utils'

export type UniversalFiltersProps = {
    rootKey: string
    group: UniversalFiltersGroup | null
    onChange: (group: UniversalFiltersGroup) => void
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    children?: React.ReactNode
    endpointFilters?: Record<string, any>
}

function UniversalFilters({
    rootKey,
    group = null,
    onChange,
    taxonomicGroupTypes,
    children,
    endpointFilters,
}: UniversalFiltersProps): JSX.Element {
    return (
        <BindLogic
            logic={universalFiltersLogic}
            props={{
                rootKey,
                group,
                onChange,
                taxonomicGroupTypes,
                endpointFilters,
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
    const { rootKey, taxonomicGroupTypes, endpointFilters } = useValues(universalFiltersLogic)
    const { replaceGroupValue } = useActions(universalFiltersLogic)

    return (
        <UniversalFilters
            key={index}
            rootKey={`${rootKey}.group_${index}`}
            group={group}
            onChange={(group) => replaceGroupValue(index, group)}
            taxonomicGroupTypes={taxonomicGroupTypes}
            endpointFilters={endpointFilters}
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
    onRemove?: () => void
    initiallyOpen?: boolean
    metadataSource?: AnyDataNode
    className?: string
    operatorAllowlist?: OperatorValueSelectProps['operatorAllowlist']
}): JSX.Element => {
    const { rootKey, taxonomicPropertyFilterGroupTypes, endpointFilters } = useValues(universalFiltersLogic)

    const isEvent = isEventFilter(filter)
    const isEditable = isEditableFilter(filter)

    const [open, setOpen] = useState<boolean>(isEditable && initiallyOpen)
    const [changingEvent, setChangingEvent] = useState<boolean>(false)

    const pageKey = `${rootKey}.filter_${index}`

    const handleChangeEvent = (
        taxonomicGroup: { type: TaxonomicFilterGroupType },
        value: TaxonomicFilterValue,
        item: any
    ): void => {
        // Keyword shortcut (e.g. "Click (autocapture)"): set the event AND attach its
        // $event_type property filter, replacing any properties the previous event had.
        if (isQuickFilterItem(item) && item.eventName) {
            onChange({
                id: item.eventName,
                name: item.eventName,
                type: EntityTypes.EVENTS,
                properties: quickFilterToPropertyFilters(item),
            })
            setChangingEvent(false)
            return
        }
        const entityType = taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type)
        if (entityType) {
            onChange({ id: value, name: item?.name ?? String(value), type: entityType, properties: [] })
        }
        setChangingEvent(false)
    }

    return (
        <Popover
            visible={open}
            onClickOutside={() => {
                setOpen(false)
                setChangingEvent(false)
            }}
            overlay={
                isEvent ? (
                    <div>
                        {changingEvent ? (
                            <TaxonomicFilter
                                onChange={handleChangeEvent}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.Events,
                                    TaxonomicFilterGroupType.Actions,
                                ]}
                                enableKeywordShortcuts
                            />
                        ) : (
                            <>
                                <div className="px-2 py-1">
                                    <LemonButton size="xsmall" type="secondary" onClick={() => setChangingEvent(true)}>
                                        Change event
                                    </LemonButton>
                                </div>
                                <LemonDivider className="my-1" />
                                <PropertyFilters
                                    pageKey={pageKey}
                                    propertyFilters={filter.properties}
                                    onChange={(properties) => onChange({ ...filter, properties })}
                                    disablePopover
                                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                    metadataSource={metadataSource}
                                />
                            </>
                        )}
                    </div>
                ) : isEditable ? (
                    <TaxonomicPropertyFilter
                        pageKey={pageKey}
                        index={0}
                        filters={[filter]}
                        onComplete={() => {
                            if (onRemove && isValidPropertyFilter(filter) && !filter.key) {
                                onRemove()
                            }
                        }}
                        setFilter={(_, property) => onChange(property)}
                        disablePopover={false}
                        taxonomicGroupTypes={taxonomicPropertyFilterGroupTypes}
                        operatorAllowlist={operatorAllowlist}
                        endpointFilters={endpointFilters}
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
                    onChange={(taxonomicGroup, value, item) => {
                        addGroupFilter(taxonomicGroup, value, item)
                        setDropdownOpen(false)
                    }}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                    enableKeywordShortcuts
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
    initialSearchQuery,
    hideSearchInput,
    searchQuery,
}: {
    fullWidth?: boolean
    onChange: () => void
    initialSearchQuery?: string
    hideSearchInput?: boolean
    searchQuery?: string
}): JSX.Element => {
    const { taxonomicGroupTypes } = useValues(universalFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    return (
        <TaxonomicFilter
            {...(fullWidth ? { width: '100%' } : {})}
            onChange={(taxonomicGroup, value, item) => {
                onChange()
                addGroupFilter(taxonomicGroup, value, item)
            }}
            taxonomicGroupTypes={taxonomicGroupTypes}
            initialSearchQuery={initialSearchQuery}
            hideSearchInput={hideSearchInput}
            searchQuery={searchQuery}
            enableKeywordShortcuts
        />
    )
}

UniversalFilters.Group = Group
UniversalFilters.Value = Value
UniversalFilters.AddFilterButton = AddFilterButton
UniversalFilters.PureTaxonomicFilter = PureTaxonomicFilter

export default UniversalFilters
