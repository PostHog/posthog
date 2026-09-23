import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import {
    LemonButton,
    LemonButtonProps,
    LemonDivider,
    LemonDropdown,
    LemonSegmentedButton,
    Popover,
} from '@posthog/lemon-ui'

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
import { isActionFilter, isEditableFilter, isEntityFilter, isEventFilter } from './utils'

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
    open: controlledOpen,
    onOpenChange,
    metadataSource,
    className,
    operatorAllowlist,
    allowEntityNegation = false,
}: {
    index: number
    filter: UniversalFilterValue
    onChange: (property: UniversalFilterValue) => void
    onRemove?: () => void
    initiallyOpen?: boolean
    /**
     * Drives the editor popover from the parent. Leave it undefined for the default behavior, where
     * the chip owns its own open state. A caller that needs to open a chip already on screen passes
     * this rather than remounting it, since a remount also resets everything else the chip holds.
     */
    open?: boolean
    onOpenChange?: (open: boolean) => void
    metadataSource?: AnyDataNode
    className?: string
    operatorAllowlist?: OperatorValueSelectProps['operatorAllowlist']
    allowEntityNegation?: boolean
}): JSX.Element => {
    const { rootKey, taxonomicPropertyFilterGroupTypes, endpointFilters } = useValues(universalFiltersLogic)

    const isEvent = isEventFilter(filter)
    const isAction = isActionFilter(filter)
    const isEditable = isEditableFilter(filter)

    const [uncontrolledOpen, setUncontrolledOpen] = useState<boolean>(isEditable && initiallyOpen)
    const open = controlledOpen !== undefined ? isEditable && controlledOpen : uncontrolledOpen
    const setOpen = (next: boolean): void => {
        setUncontrolledOpen(next)
        onOpenChange?.(next)
    }
    const [changingEvent, setChangingEvent] = useState<boolean>(false)

    // allowEntityNegation gates only the creation of new negations. Existing negation values
    // keep rendering (in UniversalFilterButton) and keep evaluating (backend applies them
    // unconditionally), so a feature flag rollback never silently flips "did not perform X"
    // back to "performed X" on saved filters.
    const negationSelect =
        allowEntityNegation && isEntityFilter(filter) ? (
            <div className="px-2 py-1" data-attr="universal-filters-entity-negation">
                <LemonSegmentedButton
                    size="xsmall"
                    value={filter.negation ? 'exclude' : 'include'}
                    onChange={(value) => onChange({ ...filter, negation: value === 'exclude' })}
                    options={[
                        {
                            value: 'include',
                            label: 'Performed',
                            'data-attr': 'universal-filters-entity-negation-include',
                        },
                        {
                            value: 'exclude',
                            label: 'Did not perform',
                            'data-attr': 'universal-filters-entity-negation-exclude',
                        },
                    ]}
                />
            </div>
        ) : null

    const pageKey = `${rootKey}.filter_${index}`

    const handleChangeEvent = (
        taxonomicGroup: { type: TaxonomicFilterGroupType },
        value: TaxonomicFilterValue,
        item: any
    ): void => {
        // changing the event intentionally resets properties, but negation belongs to the
        // chip rather than the event, so an exclusion must stay an exclusion
        const negation = isEntityFilter(filter) ? filter.negation : undefined
        // Keyword shortcut (e.g. "Click (autocapture)"): set the event AND attach its
        // $event_type property filter, replacing any properties the previous event had.
        if (isQuickFilterItem(item) && item.eventName) {
            onChange({
                id: item.eventName,
                name: item.eventName,
                type: EntityTypes.EVENTS,
                properties: quickFilterToPropertyFilters(item),
                negation,
            })
            setChangingEvent(false)
            return
        }
        const entityType = taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type)
        if (entityType) {
            onChange({ id: value, name: item?.name ?? String(value), type: entityType, properties: [], negation })
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
                                {negationSelect}
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
                ) : isAction && negationSelect ? (
                    <div>{negationSelect}</div>
                ) : null
            }
        >
            <UniversalFilterButton
                onClick={() => setOpen(!open)}
                onClose={onRemove}
                filter={filter}
                className={className}
                clickable={isAction && !!negationSelect}
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
    taxonomicFilterLogicKey,
}: {
    fullWidth?: boolean
    onChange: () => void
    initialSearchQuery?: string
    hideSearchInput?: boolean
    searchQuery?: string
    taxonomicFilterLogicKey?: string
}): JSX.Element => {
    const { taxonomicGroupTypes } = useValues(universalFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    return (
        <TaxonomicFilter
            {...(fullWidth ? { width: '100%' } : {})}
            taxonomicFilterLogicKey={taxonomicFilterLogicKey}
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
