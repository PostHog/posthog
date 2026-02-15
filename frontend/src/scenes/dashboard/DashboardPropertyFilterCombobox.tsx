import { Combobox } from '@base-ui/react/combobox'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import {
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    createDefaultPropertyFilter,
    isValidPropertyFilter,
    propertyFilterTypeToPropertyDefinitionType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { allOperatorsMapping, chooseOperatorMap, isOperatorFlag } from 'lib/utils'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyFilterValue, PropertyOperator, PropertyType } from '~/types'

import {
    DashboardPropertyFilterComboboxLogicProps,
    PropertyComboboxGroup,
    PropertyComboboxItem,
    dashboardPropertyFilterComboboxLogic,
} from './dashboardPropertyFilterComboboxLogic'

// ── Types ──

interface OperatorComboboxItem {
    id: string
    operator: PropertyOperator
    label: string
}

interface ValueComboboxItem {
    id: string
    value: string
    label: string
}

type BuilderStep =
    | { step: 'idle' }
    | { step: 'property'; previousProperty?: PropertyComboboxItem }
    | {
        step: 'operator'
        propertyItem: PropertyComboboxItem
        filterType: PropertyFilterType
        propertyType: string | null
        groupTypeIndex?: number
        previousOperator?: PropertyOperator
    }
    | {
        step: 'value'
        propertyItem: PropertyComboboxItem
        filterType: PropertyFilterType
        propertyType: string | null
        operator: PropertyOperator
        groupTypeIndex?: number
    }

type EditingState = null | { filterIndex: number; field: 'property' | 'operator' | 'value' }

// ── Props ──

interface DashboardPropertyFilterComboboxProps {
    properties: AnyPropertyFilter[] | undefined
    onChange: (properties: AnyPropertyFilter[]) => void
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    eventNames?: string[]
    schemaColumns?: DatabaseSchemaField[]
    size?: 'xsmall' | 'small' | 'medium'
}

// ── Helpers ──

function filterGroups(groups: PropertyComboboxGroup[], search: string): PropertyComboboxGroup[] {
    if (!search) {
        return groups
    }
    const lower = search.toLowerCase()
    return groups
        .map((group) => ({
            ...group,
            items: group.items.filter(
                (item) => item.name.toLowerCase().includes(lower) || String(item.value).toLowerCase().includes(lower)
            ),
        }))
        .filter((g) => g.items.length > 0)
}

function filterOperatorItems(items: OperatorComboboxItem[], search: string): OperatorComboboxItem[] {
    if (!search) {
        return items
    }
    const lower = search.toLowerCase()
    return items.filter((item) => item.label.toLowerCase().includes(lower))
}

function filterValueItems(items: ValueComboboxItem[], search: string): ValueComboboxItem[] {
    if (!search) {
        return items
    }
    const lower = search.toLowerCase()
    return items.filter((item) => item.label.toLowerCase().includes(lower))
}

const CHIP_BASE =
    'inline-flex items-center bg-fill-button-tertiary px-1.5 py-0.5 font-medium max-w-[200px] ring-1 ring-secondary text-xs'

function valueChipRounding(index: number, total: number, connectedLeft = false): string {
    if (total === 1) {
        return connectedLeft ? 'rounded-l-none rounded-r-sm' : 'rounded-sm'
    }
    if (index === 0) {
        return connectedLeft ? 'rounded-none' : 'rounded-l-sm rounded-r-none'
    }
    if (index === total - 1) {
        return 'rounded-l-none rounded-r-sm'
    }
    return 'rounded-none'
}

// ── Outer wrapper ──

export function DashboardPropertyFilterCombobox({
    properties,
    onChange,
    taxonomicGroupTypes,
    eventNames = [],
    schemaColumns = [],
}: DashboardPropertyFilterComboboxProps): JSX.Element {
    const taxonomicFilterLogicKey = 'dashboardPropertyFilterCombobox'

    const comboboxLogicProps: DashboardPropertyFilterComboboxLogicProps = {
        taxonomicGroupTypes,
        eventNames,
        schemaColumns,
        taxonomicFilterLogicKey,
    }

    return (
        <BindLogic logic={dashboardPropertyFilterComboboxLogic} props={comboboxLogicProps}>
            <DashboardPropertyFilterComboboxInner properties={properties || []} onChange={onChange} />
        </BindLogic>
    )
}

// ── Inner component ──

interface DashboardPropertyFilterComboboxInnerProps {
    properties: AnyPropertyFilter[]
    onChange: (properties: AnyPropertyFilter[]) => void
}

function DashboardPropertyFilterComboboxInner({
    properties,
    onChange,
}: DashboardPropertyFilterComboboxInnerProps): JSX.Element {
    const { rawGroupedItems, allRawItems, hasHogQLGroup, remoteResultsLoading } = useValues(
        dashboardPropertyFilterComboboxLogic
    )
    const { loadRemoteResults } = useActions(dashboardPropertyFilterComboboxLogic)
    const { describeProperty } = useValues(propertyDefinitionsModel)

    const hasLoadedRemote = useRef(false)
    const [builderStep, setBuilderStep] = useState<BuilderStep>({ step: 'idle' })
    const [editingState, setEditingState] = useState<EditingState>(null)

    const ensureRemoteLoaded = useCallback(() => {
        if (!hasLoadedRemote.current) {
            hasLoadedRemote.current = true
            loadRemoteResults({})
        }
    }, [loadRemoteResults])

    const validProperties = properties.filter(isValidPropertyFilter)

    // ── Commit helpers ──

    const commitFilter = useCallback(
        (
            propertyItem: PropertyComboboxItem,
            filterType: PropertyFilterType,
            operator: PropertyOperator,
            value: PropertyFilterValue
        ) => {
            const newFilter = createDefaultPropertyFilter(
                null,
                propertyItem.value as string | number,
                filterType,
                propertyItem.taxonomicGroup,
                describeProperty
            )
            const withOperatorAndValue = { ...newFilter, operator, value } as AnyPropertyFilter
            onChange([...properties, withOperatorAndValue])
            setBuilderStep({ step: 'idle' })
        },
        [properties, onChange, describeProperty]
    )

    const commitFlagFilter = useCallback(
        (propertyItem: PropertyComboboxItem, filterType: PropertyFilterType, operator: PropertyOperator) => {
            const newFilter = createDefaultPropertyFilter(
                null,
                propertyItem.value as string | number,
                filterType,
                propertyItem.taxonomicGroup,
                describeProperty
            )
            const withOperator = { ...newFilter, operator, value: null } as AnyPropertyFilter
            onChange([...properties, withOperator])
            setBuilderStep({ step: 'idle' })
        },
        [properties, onChange, describeProperty]
    )

    const handleHogQLSubmit = useCallback(
        (value: string | number | null) => {
            if (!value) {
                return
            }
            const hogQLFilter: AnyPropertyFilter = {
                type: PropertyFilterType.HogQL,
                key: String(value),
                value: null,
            }
            onChange([...properties, hogQLFilter])
        },
        [properties, onChange]
    )

    const updateFilterOperator = useCallback(
        (index: number, operator: PropertyOperator) => {
            const updated = [...properties]
            const filter = updated[index]
            if (isOperatorFlag(operator)) {
                updated[index] = { ...filter, operator, value: null } as AnyPropertyFilter
            } else {
                updated[index] = { ...filter, operator } as AnyPropertyFilter
            }
            onChange(updated)
            setEditingState(null)
        },
        [properties, onChange]
    )

    const updateFilterValue = useCallback(
        (index: number, value: PropertyFilterValue) => {
            const updated = [...properties]
            updated[index] = { ...updated[index], value } as AnyPropertyFilter
            onChange(updated)
            setEditingState(null)
        },
        [properties, onChange]
    )

    const updateFilterProperty = useCallback(
        (index: number, item: PropertyComboboxItem) => {
            const filterType = taxonomicFilterTypeToPropertyFilterType(item.groupType)
            if (!filterType || item.value == null) {
                return
            }
            const newFilter = createDefaultPropertyFilter(
                null,
                item.value as string | number,
                filterType,
                item.taxonomicGroup,
                describeProperty
            )
            const updated = [...properties]
            updated[index] = newFilter
            onChange(updated)
            setEditingState(null)
        },
        [properties, onChange, describeProperty]
    )

    const handleRemoveFilter = useCallback(
        (index: number) => {
            onChange(properties.filter((_, i) => i !== index))
        },
        [properties, onChange]
    )

    // ── State machine transitions ──

    const handlePropertySelect = useCallback(
        (item: PropertyComboboxItem | null) => {
            if (!item) {
                return
            }
            const filterType = taxonomicFilterTypeToPropertyFilterType(item.groupType)
            if (!filterType || item.value == null) {
                return
            }
            const apiType = propertyFilterTypeToPropertyDefinitionType(filterType)
            const groupTypeIndex =
                'group_type_index' in item.taxonomicGroup ? (item.taxonomicGroup as any).group_type_index : undefined
            const propertyType = describeProperty(item.value, apiType, groupTypeIndex)
            setBuilderStep({
                step: 'operator',
                propertyItem: item,
                filterType,
                propertyType,
                groupTypeIndex,
            })
        },
        [describeProperty]
    )

    const handleOperatorSelect = useCallback(
        (opItem: OperatorComboboxItem | null) => {
            if (!opItem || builderStep.step !== 'operator') {
                return
            }
            if (isOperatorFlag(opItem.operator)) {
                commitFlagFilter(builderStep.propertyItem, builderStep.filterType, opItem.operator)
            } else {
                setBuilderStep({
                    step: 'value',
                    propertyItem: builderStep.propertyItem,
                    filterType: builderStep.filterType,
                    propertyType: builderStep.propertyType,
                    operator: opItem.operator,
                    groupTypeIndex: builderStep.groupTypeIndex,
                })
            }
        },
        [builderStep, commitFlagFilter]
    )

    const handleValuesCommit = useCallback(
        (values: string[]) => {
            if (values.length === 0 || builderStep.step !== 'value') {
                return
            }
            const filterValue = values.length === 1 ? values[0] : values
            commitFilter(builderStep.propertyItem, builderStep.filterType, builderStep.operator, filterValue)
        },
        [builderStep, commitFilter]
    )

    const handleOperatorStepBack = useCallback(
        (mode: 'fresh' | 'keep') => {
            if (builderStep.step !== 'operator') {
                return
            }
            setBuilderStep({
                step: 'property',
                previousProperty: mode === 'keep' ? builderStep.propertyItem : undefined,
            })
        },
        [builderStep]
    )

    const handleValueStepBack = useCallback(
        (mode: 'fresh' | 'keep') => {
            if (builderStep.step !== 'value') {
                return
            }
            setBuilderStep({
                step: 'operator',
                propertyItem: builderStep.propertyItem,
                filterType: builderStep.filterType,
                propertyType: builderStep.propertyType,
                groupTypeIndex: builderStep.groupTypeIndex,
                previousOperator: mode === 'keep' ? builderStep.operator : undefined,
            })
        },
        [builderStep]
    )

    const handleGoToPropertyFromValue = useCallback(() => {
        if (builderStep.step !== 'value') {
            return
        }
        setBuilderStep({
            step: 'property',
            previousProperty: builderStep.propertyItem,
        })
    }, [builderStep])

    return (
        <div className="group input-like flex gap-1 items-center flex-wrap relative w-full bg-fill-input border border-primary focus-within:ring-primary py-2 px-2 cursor-text my-10">
            <span className="border-r pr-1 text-xs whitespace-nowrap shrink-0">Filters:</span>

            {/* Completed filter chips */}
            {validProperties.map((filter, index) => (
                <CompletedFilterChips
                    key={`${filter.key}-${index}`}
                    filter={filter}
                    index={index}
                    editingState={editingState}
                    allRawItems={allRawItems}
                    rawGroupedItems={rawGroupedItems}
                    remoteResultsLoading={remoteResultsLoading}
                    onEditField={(field) => setEditingState({ filterIndex: index, field })}
                    onCloseEdit={() => setEditingState(null)}
                    onUpdateProperty={(item) => updateFilterProperty(index, item)}
                    onUpdateOperator={(op) => updateFilterOperator(index, op)}
                    onUpdateValue={(val) => updateFilterValue(index, val)}
                    onRemove={() => handleRemoveFilter(index)}
                    onEnsureRemoteLoaded={ensureRemoteLoaded}
                />
            ))}

            {/* Builder: grouped pending chips + active input */}
            {(builderStep.step === 'idle' || builderStep.step === 'property') && (
                <PropertyStepCombobox
                    allRawItems={allRawItems}
                    rawGroupedItems={rawGroupedItems}
                    remoteResultsLoading={remoteResultsLoading}
                    hasHogQLGroup={hasHogQLGroup}
                    previousProperty={
                        builderStep.step === 'property' ? builderStep.previousProperty : undefined
                    }
                    onSelect={handlePropertySelect}
                    onHogQLSubmit={handleHogQLSubmit}
                    onOpen={ensureRemoteLoaded}
                />
            )}
            {builderStep.step === 'operator' && (
                <div className="inline-flex items-center gap-px">
                    <button
                        type="button"
                        className={`${CHIP_BASE} rounded-l-sm rounded-r-none cursor-pointer hover:bg-fill-button-tertiary-hover`}
                        onClick={() => handleOperatorStepBack('keep')}
                    >
                        <PropertyKeyInfo
                            value={builderStep.propertyItem.name}
                            disablePopover
                            type={builderStep.propertyItem.groupType}
                        />
                    </button>
                    <OperatorStepCombobox
                        propertyType={builderStep.propertyType as PropertyType | undefined}
                        previousOperator={builderStep.previousOperator}
                        onSelect={handleOperatorSelect}
                        onDismiss={() => setBuilderStep({ step: 'idle' })}
                        onStepBack={handleOperatorStepBack}
                    />
                </div>
            )}
            {builderStep.step === 'value' && (
                <div className="inline-flex items-center gap-px">
                    <button
                        type="button"
                        className={`${CHIP_BASE} rounded-l-sm rounded-r-none cursor-pointer hover:bg-fill-button-tertiary-hover`}
                        onClick={handleGoToPropertyFromValue}
                    >
                        <PropertyKeyInfo
                            value={builderStep.propertyItem.name}
                            disablePopover
                            type={builderStep.propertyItem.groupType}
                        />
                    </button>
                    <button
                        type="button"
                        className={`${CHIP_BASE} rounded-none cursor-pointer hover:bg-fill-button-tertiary-hover`}
                        onClick={() => handleValueStepBack('keep')}
                    >
                        {allOperatorsMapping[builderStep.operator] || builderStep.operator}
                    </button>
                    <ValueStepCombobox
                        propertyKey={String(builderStep.propertyItem.value)}
                        filterType={builderStep.filterType}
                        groupTypeIndex={builderStep.groupTypeIndex}
                        onCommitValues={handleValuesCommit}
                        onDismiss={() => setBuilderStep({ step: 'idle' })}
                        onStepBack={handleValueStepBack}
                    />
                </div>
            )}
        </div>
    )
}

// ── Property Step Combobox ──

function PropertyStepCombobox({
    allRawItems,
    rawGroupedItems,
    remoteResultsLoading,
    hasHogQLGroup,
    previousProperty,
    onSelect,
    onHogQLSubmit,
    onOpen,
}: {
    allRawItems: PropertyComboboxItem[]
    rawGroupedItems: PropertyComboboxGroup[]
    remoteResultsLoading: boolean
    hasHogQLGroup: boolean
    previousProperty?: PropertyComboboxItem
    onSelect: (item: PropertyComboboxItem | null) => void
    onHogQLSubmit: (value: string | number | null) => void
    onOpen: () => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null!)
    const selectedRef = useRef(false)
    const [searchValue, setSearchValue] = useState(previousProperty?.name ?? '')

    const filteredGroups = useMemo(() => filterGroups(rawGroupedItems, searchValue), [rawGroupedItems, searchValue])
    const filteredItems = useMemo(() => filteredGroups.flatMap((g) => g.items), [filteredGroups])

    const handleOpenChange = useCallback(
        (open: boolean) => {
            if (open) {
                onOpen()
            }
            if (!open && !selectedRef.current && !previousProperty) {
                // Normal idle dismiss — do nothing special
            }
            selectedRef.current = false
        },
        [onOpen, previousProperty]
    )

    useEffect(() => {
        if (previousProperty) {
            onOpen()
            requestAnimationFrame(() => {
                inputRef.current?.focus()
                inputRef.current?.select()
            })
        }
    }, [previousProperty, onOpen])

    return (
        <Combobox.Root<PropertyComboboxItem>
            items={allRawItems}
            filteredItems={filteredItems}
            filter={null}
            value={previousProperty ?? null}
            onValueChange={(item) => {
                selectedRef.current = true
                onSelect(item)
            }}
            isItemEqualToValue={(a, b) => a?.id === b?.id}
            itemToStringLabel={(item) => item?.name ?? ''}
            itemToStringValue={(item) => item?.id ?? ''}
            onOpenChange={handleOpenChange}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            open={!!previousProperty ? true : undefined}
            autoHighlight
        >
            <Combobox.Input
                ref={inputRef}
                aria-label="Search property filters"
                placeholder="Add filter..."
                className="flex-1 min-w-[80px] px-1 py-0.5 text-sm focus:outline-none border-transparent bg-transparent"
            />
            <Combobox.Portal>
                <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4} align="start">
                    <Combobox.Popup className="primitive-menu-content min-w-[300px] flex flex-col max-h-[min(400px,var(--available-height))]">
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-px p-1">
                                {filteredGroups.map((group) => (
                                    <Combobox.Group key={group.type} className="flex flex-col gap-px">
                                        <Combobox.GroupLabel className="px-2 py-1 sticky top-0 bg-surface-primary z-1">
                                            <Label intent="menu">{group.name}</Label>
                                        </Combobox.GroupLabel>
                                        {group.items.map((item) => {
                                            const isActive = previousProperty?.id === item.id
                                            return (
                                                <Combobox.Item
                                                    key={item.id}
                                                    value={item}
                                                    render={(props) => (
                                                        <ButtonPrimitive
                                                            {...props}
                                                            menuItem
                                                            fullWidth
                                                            active={isActive}
                                                        >
                                                            {isActive ? (
                                                                <IconCheck className="size-4 text-success shrink-0" />
                                                            ) : (
                                                                item.icon && (
                                                                    <span className="shrink-0">{item.icon}</span>
                                                                )
                                                            )}
                                                            <span className="truncate flex-1">
                                                                <PropertyKeyInfo
                                                                    value={item.name}
                                                                    disablePopover
                                                                    type={item.groupType}
                                                                />
                                                            </span>
                                                        </ButtonPrimitive>
                                                    )}
                                                />
                                            )
                                        })}
                                    </Combobox.Group>
                                ))}

                                {filteredGroups.length === 0 && !remoteResultsLoading && (
                                    <div className="px-3 py-4 text-center text-sm text-muted">
                                        {searchValue ? 'No results found' : 'No properties available'}
                                    </div>
                                )}
                                {remoteResultsLoading && filteredGroups.length === 0 && (
                                    <div className="px-3 py-4 text-center text-sm text-muted">Loading...</div>
                                )}
                            </Combobox.List>

                            {hasHogQLGroup && (
                                <div className="border-t border-primary">
                                    <div className="px-2 py-1">
                                        <Label intent="menu">SQL expression</Label>
                                    </div>
                                    <div className="px-2 pb-2">
                                        <HogQLEditor
                                            onChange={onHogQLSubmit}
                                            value=""
                                            submitText="Add SQL expression"
                                            disableAutoFocus
                                        />
                                    </div>
                                </div>
                            )}
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}

// ── Operator Step Combobox ──

function OperatorStepCombobox({
    propertyType,
    previousOperator,
    onSelect,
    onDismiss,
    onStepBack,
}: {
    propertyType: PropertyType | undefined
    previousOperator?: PropertyOperator
    onSelect: (item: OperatorComboboxItem | null) => void
    onDismiss: () => void
    onStepBack: (mode: 'fresh' | 'keep') => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null!)
    const [searchValue, setSearchValue] = useState('')
    const selectedRef = useRef(false)

    const operatorItems = useMemo((): OperatorComboboxItem[] => {
        const map = chooseOperatorMap(propertyType)
        return Object.entries(map).map(([key, label]) => ({
            id: key,
            operator: key as PropertyOperator,
            label,
        }))
    }, [propertyType])

    const filteredItems = useMemo(() => filterOperatorItems(operatorItems, searchValue), [operatorItems, searchValue])

    const currentValue = useMemo(
        () => (previousOperator ? operatorItems.find((i) => i.operator === previousOperator) ?? null : null),
        [previousOperator, operatorItems]
    )

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent<HTMLInputElement>) => {
            const input = e.currentTarget
            if (input.selectionStart === 0 && !searchValue) {
                if (e.key === 'Backspace') {
                    e.preventDefault()
                    onStepBack('fresh')
                } else if (e.key === 'ArrowLeft') {
                    e.preventDefault()
                    onStepBack('keep')
                }
            }
        },
        [searchValue, onStepBack]
    )

    useEffect(() => {
        requestAnimationFrame(() => inputRef.current?.focus())
    }, [])

    return (
        <Combobox.Root<OperatorComboboxItem>
            items={operatorItems}
            filteredItems={filteredItems}
            filter={null}
            value={currentValue}
            onValueChange={(item) => {
                selectedRef.current = true
                onSelect(item)
            }}
            isItemEqualToValue={(a, b) => a?.id === b?.id}
            itemToStringLabel={(item) => item?.label ?? ''}
            itemToStringValue={(item) => item?.id ?? ''}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            open
            onOpenChange={(open) => {
                if (!open && !selectedRef.current) {
                    onDismiss()
                }
                selectedRef.current = false
            }}
            autoHighlight
        >
            <Combobox.Input
                ref={inputRef}
                aria-label="Select operator"
                placeholder="Operator..."
                className="flex-1 min-w-[80px] px-1 py-0.5 text-sm focus:outline-none border-transparent bg-transparent"
                onKeyDown={handleKeyDown}
            />
            <Combobox.Portal>
                <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4} align="start">
                    <Combobox.Popup className="primitive-menu-content min-w-[200px] flex flex-col max-h-[min(300px,var(--available-height))]">
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-px p-1">
                                {filteredItems.map((item) => (
                                    <Combobox.Item
                                        key={item.id}
                                        value={item}
                                        render={(props) => (
                                            <ButtonPrimitive {...props} menuItem fullWidth>
                                                <span className="truncate flex-1">{item.label}</span>
                                            </ButtonPrimitive>
                                        )}
                                    />
                                ))}
                                {filteredItems.length === 0 && (
                                    <div className="px-3 py-4 text-center text-sm text-muted">No operators found</div>
                                )}
                            </Combobox.List>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}

// ── Value Step Combobox ──

function ValueStepCombobox({
    propertyKey,
    filterType,
    groupTypeIndex: _groupTypeIndex,
    onCommitValues,
    onDismiss,
    onStepBack,
}: {
    propertyKey: string
    filterType: PropertyFilterType
    groupTypeIndex?: number
    onCommitValues: (values: string[]) => void
    onDismiss: () => void
    onStepBack: (mode: 'fresh' | 'keep') => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null!)
    const [searchValue, setSearchValue] = useState('')
    const [selectedValues, setSelectedValues] = useState<ValueComboboxItem[]>([])
    const committedRef = useRef(false)
    const justSelectedRef = useRef(false)

    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(filterType)

    useEffect(() => {
        loadPropertyValues({
            endpoint: undefined,
            type: propertyDefinitionType,
            newInput: '',
            propertyKey,
            eventNames: [],
        })
    }, [loadPropertyValues, propertyDefinitionType, propertyKey])

    useEffect(() => {
        if (searchValue) {
            loadPropertyValues({
                endpoint: undefined,
                type: propertyDefinitionType,
                newInput: searchValue,
                propertyKey,
                eventNames: [],
            })
        }
    }, [searchValue, loadPropertyValues, propertyDefinitionType, propertyKey])

    const valueItems = useMemo((): ValueComboboxItem[] => {
        const propValues = options[propertyKey]?.values || []
        return propValues.map((v: any) => ({
            id: String(v.name ?? v),
            value: String(v.name ?? v),
            label: String(v.name ?? v),
        }))
    }, [options, propertyKey])

    const filteredItems = useMemo(() => filterValueItems(valueItems, searchValue), [valueItems, searchValue])

    const selectedIds = useMemo(() => new Set(selectedValues.map((v) => v.value)), [selectedValues])

    const allItems = useMemo(() => {
        const alreadyExists =
            filteredItems.some((i) => i.value === searchValue) || selectedValues.some((i) => i.value === searchValue)
        if (searchValue && !alreadyExists) {
            return [{ id: `custom::${searchValue}`, value: searchValue, label: searchValue }, ...filteredItems]
        }
        return filteredItems
    }, [filteredItems, searchValue, selectedValues])

    const handleValueChange = useCallback((newValues: ValueComboboxItem[]) => {
        justSelectedRef.current = true
        setSelectedValues(newValues)
        setTimeout(() => {
            justSelectedRef.current = false
        }, 0)
    }, [])

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent<HTMLInputElement>) => {
            const input = e.currentTarget
            if (input.selectionStart === 0 && !searchValue && selectedValues.length === 0) {
                if (e.key === 'Backspace') {
                    e.preventDefault()
                    committedRef.current = true
                    onStepBack('fresh')
                } else if (e.key === 'ArrowLeft') {
                    e.preventDefault()
                    committedRef.current = true
                    onStepBack('keep')
                }
            }
        },
        [searchValue, selectedValues, onStepBack]
    )

    useEffect(() => {
        requestAnimationFrame(() => inputRef.current?.focus())
    }, [])

    return (
        <Combobox.Root
            multiple
            items={valueItems}
            filteredItems={allItems}
            filter={null}
            value={selectedValues}
            onValueChange={handleValueChange}
            isItemEqualToValue={(a, b) => a?.value === b?.value}
            itemToStringLabel={(item) => item?.label ?? ''}
            itemToStringValue={(item) => item?.id ?? ''}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            open
            onOpenChange={(open) => {
                if (!open && !committedRef.current && !justSelectedRef.current) {
                    if (selectedValues.length > 0) {
                        onCommitValues(selectedValues.map((v) => v.value))
                    } else {
                        onDismiss()
                    }
                }
            }}
            autoHighlight
        >
            <Combobox.Chips className="contents">
                <Combobox.Value>
                    {(values: ValueComboboxItem[]) =>
                        values.map((item, i) => (
                            <Combobox.Chip
                                key={item.id}
                                className={`${CHIP_BASE} ${valueChipRounding(i, values.length, true)} gap-0.5 cursor-default outline-none focus-visible:bg-fill-button-tertiary-active`}
                            >
                                {item.label}
                                <Combobox.ChipRemove
                                    className="inline-flex items-center justify-center size-3.5 rounded-sm hover:bg-fill-button-tertiary-hover cursor-pointer"
                                    aria-label={`Remove ${item.label}`}
                                >
                                    <IconX className="size-2.5 text-tertiary" />
                                </Combobox.ChipRemove>
                            </Combobox.Chip>
                        ))
                    }
                </Combobox.Value>
                <Combobox.Input
                    ref={inputRef}
                    aria-label="Select values"
                    placeholder={selectedValues.length === 0 ? 'Value...' : ''}
                    className="flex-1 min-w-[60px] px-1 py-0.5 text-sm focus:outline-none border-transparent bg-transparent"
                    onKeyDown={handleKeyDown}
                />
            </Combobox.Chips>
            <Combobox.Portal>
                <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4} align="start">
                    <Combobox.Popup className="primitive-menu-content min-w-[200px] flex flex-col max-h-[min(300px,var(--available-height))]">
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-px p-1">
                                {allItems.map((item) => {
                                    const isSelected = selectedIds.has(item.value)
                                    return (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            render={(props) => (
                                                <ButtonPrimitive {...props} menuItem fullWidth active={isSelected}>
                                                    {isSelected && (
                                                        <IconCheck className="size-4 text-success shrink-0" />
                                                    )}
                                                    <span className="truncate flex-1">
                                                        {item.id.startsWith('custom::')
                                                            ? `Create "${item.label}"`
                                                            : item.label}
                                                    </span>
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )
                                })}
                                {allItems.length === 0 && (
                                    <ButtonPrimitive fullWidth className="text-tertiary">
                                        {options[propertyKey]?.status === 'loading' ? (
                                            <span className="italic flex items-center gap-1">
                                                <Spinner size="small" /> Loading...
                                            </span>
                                        ) : (
                                            <span className="italic">Type a value</span>
                                        )}
                                    </ButtonPrimitive>
                                )}
                            </Combobox.List>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}

// ── Completed Filter Chips ──

function CompletedFilterChips({
    filter,
    index,
    editingState,
    allRawItems,
    rawGroupedItems,
    remoteResultsLoading,
    onEditField,
    onCloseEdit,
    onUpdateProperty,
    onUpdateOperator,
    onUpdateValue,
    onRemove,
    onEnsureRemoteLoaded,
}: {
    filter: AnyPropertyFilter
    index: number
    editingState: EditingState
    allRawItems: PropertyComboboxItem[]
    rawGroupedItems: PropertyComboboxGroup[]
    remoteResultsLoading: boolean
    onEditField: (field: 'property' | 'operator' | 'value') => void
    onCloseEdit: () => void
    onUpdateProperty: (item: PropertyComboboxItem) => void
    onUpdateOperator: (op: PropertyOperator) => void
    onUpdateValue: (val: PropertyFilterValue) => void
    onRemove: () => void
    onEnsureRemoteLoaded: () => void
}): JSX.Element {
    const { describeProperty } = useValues(propertyDefinitionsModel)

    const filterType = filter.type as PropertyFilterType
    const taxonomicGroupType = PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filterType]
    const operator = 'operator' in filter ? (filter.operator as PropertyOperator) : undefined
    const value = 'value' in filter ? filter.value : undefined
    const operatorLabel = operator ? allOperatorsMapping[operator] || operator : ''
    const isHogQL = filterType === PropertyFilterType.HogQL

    const isEditingProperty = editingState?.filterIndex === index && editingState.field === 'property'
    const isEditingOperator = editingState?.filterIndex === index && editingState.field === 'operator'
    const isEditingValue = editingState?.filterIndex === index && editingState.field === 'value'

    const apiType = propertyFilterTypeToPropertyDefinitionType(filterType)
    const groupTypeIndex = 'group_type_index' in filter ? (filter.group_type_index ?? undefined) : undefined
    const propertyType = describeProperty(String(filter.key), apiType, groupTypeIndex) as PropertyType | undefined

    const isFlagOp = operator ? isOperatorFlag(operator) : false

    const valueArray = useMemo((): string[] => {
        if (value === null || value === undefined) {
            return []
        }
        if (Array.isArray(value)) {
            return value.map(String)
        }
        return [String(value)]
    }, [value])

    if (isHogQL) {
        return (
            <div className="border border-secondary rounded p-1 inline-flex items-center gap-px mr-1">
                <span className={`${CHIP_BASE} rounded-sm`}>
                    <PropertyKeyInfo value={String(filter.key)} disablePopover type={taxonomicGroupType} />
                </span>
                <ButtonPrimitive
                    className="size-5 flex items-center justify-center rounded-sm hover:bg-fill-button-tertiary-hover cursor-pointer shrink-0"
                    onClick={onRemove}
                    aria-label={`Remove filter ${filter.key}`}
                >
                    <IconX className="size-3 text-tertiary" />
                </ButtonPrimitive>
            </div>
        )
    }

    return (
        <div className="border border-secondary rounded-lg p-1 inline-flex items-center gap-1 mr-1">
            {/* Property chip or editor */}
            {isEditingProperty ? (
                <InlinePropertyCombobox
                    allRawItems={allRawItems}
                    rawGroupedItems={rawGroupedItems}
                    remoteResultsLoading={remoteResultsLoading}
                    currentPropertyKey={String(filter.key)}
                    onSelect={(item) => onUpdateProperty(item)}
                    onDismiss={onCloseEdit}
                    onOpen={onEnsureRemoteLoaded}
                />
            ) : (
                <button
                    type="button"
                    className={`${CHIP_BASE} rounded-sm cursor-pointer hover:bg-fill-button-tertiary-hover`}
                    onClick={() => onEditField('property')}
                >
                    <PropertyKeyInfo value={String(filter.key)} disablePopover type={taxonomicGroupType} />
                </button>
            )}

            {/* Operator — plain text, no chip styling */}
            {isEditingOperator ? (
                <InlineOperatorCombobox
                    propertyType={propertyType}
                    currentOperator={operator}
                    onSelect={(op) => onUpdateOperator(op)}
                    onDismiss={onCloseEdit}
                />
            ) : (
                <button
                    type="button"
                    className="text-xs text-muted cursor-pointer hover:text-default px-0.5"
                    onClick={() => onEditField('operator')}
                >
                    {operatorLabel}
                </button>
            )}

            {/* Value chips or editor (skip for flag operators) — single click target */}
            {!isFlagOp && (
                <>
                    {isEditingValue ? (
                        <InlineValueCombobox
                            propertyKey={String(filter.key)}
                            filterType={filterType}
                            groupTypeIndex={groupTypeIndex}
                            currentValues={valueArray}
                            onCommit={(val) => onUpdateValue(val)}
                            onDismiss={onCloseEdit}
                        />
                    ) : valueArray.length > 0 ? (
                        <button
                            type="button"
                            className="inline-flex items-center gap-px cursor-pointer"
                            onClick={() => onEditField('value')}
                        >
                            {valueArray.map((val, i) => (
                                <span
                                    key={i}
                                    className={`${CHIP_BASE} ${valueChipRounding(i, valueArray.length)} hover:bg-fill-button-tertiary-hover`}
                                >
                                    {val}
                                </span>
                            ))}
                        </button>
                    ) : (
                        <button
                            type="button"
                            className={`${CHIP_BASE} rounded-sm cursor-pointer hover:bg-fill-button-tertiary-hover`}
                            onClick={() => onEditField('value')}
                        >
                            <span className="text-muted italic">none</span>
                        </button>
                    )}
                </>
            )}

            <ButtonPrimitive
                className="size-5 flex items-center justify-center rounded-sm hover:bg-fill-button-tertiary-hover cursor-pointer shrink-0"
                onClick={onRemove}
                aria-label={`Remove filter ${filter.key}`}
            >
                <IconX className="size-3 text-tertiary" />
            </ButtonPrimitive>
        </div>
    )
}

// ── Inline Property Combobox (for editing completed chips) ──

function InlinePropertyCombobox({
    allRawItems,
    rawGroupedItems,
    remoteResultsLoading,
    currentPropertyKey,
    onSelect,
    onDismiss,
    onOpen,
}: {
    allRawItems: PropertyComboboxItem[]
    rawGroupedItems: PropertyComboboxGroup[]
    remoteResultsLoading: boolean
    currentPropertyKey: string
    onSelect: (item: PropertyComboboxItem) => void
    onDismiss: () => void
    onOpen: () => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null!)
    const selectedRef = useRef(false)

    const currentItem = useMemo(
        () => allRawItems.find((i) => String(i.value) === currentPropertyKey) ?? null,
        [allRawItems, currentPropertyKey]
    )

    const [searchValue, setSearchValue] = useState(currentItem?.name ?? '')

    const filteredGroups = useMemo(() => filterGroups(rawGroupedItems, searchValue), [rawGroupedItems, searchValue])
    const filteredItems = useMemo(() => filteredGroups.flatMap((g) => g.items), [filteredGroups])

    useEffect(() => {
        onOpen()
        requestAnimationFrame(() => {
            inputRef.current?.focus()
            inputRef.current?.select()
        })
    }, [onOpen])

    return (
        <Combobox.Root<PropertyComboboxItem>
            items={allRawItems}
            filteredItems={filteredItems}
            filter={null}
            value={currentItem}
            onValueChange={(item) => {
                if (item) {
                    selectedRef.current = true
                    onSelect(item)
                }
            }}
            isItemEqualToValue={(a, b) => a?.id === b?.id}
            itemToStringLabel={(item) => item?.name ?? ''}
            itemToStringValue={(item) => item?.id ?? ''}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            open
            onOpenChange={(open) => {
                if (!open && !selectedRef.current) {
                    onDismiss()
                }
                selectedRef.current = false
            }}
            autoHighlight
        >
            <Combobox.Input
                ref={inputRef}
                aria-label="Change property"
                placeholder="Property..."
                className={`${CHIP_BASE} rounded-l-sm rounded-r-none min-w-[80px] max-w-[200px] focus:outline-none`}
            />
            <Combobox.Portal>
                <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4} align="start">
                    <Combobox.Popup className="primitive-menu-content min-w-[300px] flex flex-col max-h-[min(400px,var(--available-height))]">
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-px p-1">
                                {filteredGroups.map((group) => (
                                    <Combobox.Group key={group.type} className="flex flex-col gap-px">
                                        <Combobox.GroupLabel className="px-2 py-1 sticky top-0 bg-surface-primary z-1">
                                            <Label intent="menu">{group.name}</Label>
                                        </Combobox.GroupLabel>
                                        {group.items.map((item) => {
                                            const isActive = currentItem?.id === item.id
                                            return (
                                                <Combobox.Item
                                                    key={item.id}
                                                    value={item}
                                                    render={(props) => (
                                                        <ButtonPrimitive
                                                            {...props}
                                                            menuItem
                                                            fullWidth
                                                            active={isActive}
                                                        >
                                                            {isActive ? (
                                                                <IconCheck className="size-4 text-success shrink-0" />
                                                            ) : (
                                                                item.icon && (
                                                                    <span className="shrink-0">{item.icon}</span>
                                                                )
                                                            )}
                                                            <span className="truncate flex-1">
                                                                <PropertyKeyInfo
                                                                    value={item.name}
                                                                    disablePopover
                                                                    type={item.groupType}
                                                                />
                                                            </span>
                                                        </ButtonPrimitive>
                                                    )}
                                                />
                                            )
                                        })}
                                    </Combobox.Group>
                                ))}
                                {filteredGroups.length === 0 && !remoteResultsLoading && (
                                    <div className="px-3 py-4 text-center text-sm text-muted">
                                        {searchValue ? 'No results found' : 'No properties available'}
                                    </div>
                                )}
                                {remoteResultsLoading && filteredGroups.length === 0 && (
                                    <div className="px-3 py-4 text-center text-sm text-muted">Loading...</div>
                                )}
                            </Combobox.List>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}

// ── Inline Operator Combobox (for editing completed chips) ──

function InlineOperatorCombobox({
    propertyType,
    currentOperator,
    onSelect,
    onDismiss,
}: {
    propertyType: PropertyType | undefined
    currentOperator: PropertyOperator | undefined
    onSelect: (op: PropertyOperator) => void
    onDismiss: () => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null!)
    const selectedRef = useRef(false)

    const operatorItems = useMemo((): OperatorComboboxItem[] => {
        const map = chooseOperatorMap(propertyType)
        return Object.entries(map).map(([key, label]) => ({
            id: key,
            operator: key as PropertyOperator,
            label,
        }))
    }, [propertyType])

    const currentItem = useMemo(
        () => (currentOperator ? operatorItems.find((i) => i.operator === currentOperator) ?? null : null),
        [currentOperator, operatorItems]
    )

    const [searchValue, setSearchValue] = useState(currentItem?.label ?? '')

    const filteredItems = useMemo(() => filterOperatorItems(operatorItems, searchValue), [operatorItems, searchValue])

    useEffect(() => {
        requestAnimationFrame(() => {
            inputRef.current?.focus()
            inputRef.current?.select()
        })
    }, [])

    return (
        <Combobox.Root<OperatorComboboxItem>
            items={operatorItems}
            filteredItems={filteredItems}
            filter={null}
            value={currentItem}
            onValueChange={(item) => {
                if (item) {
                    selectedRef.current = true
                    onSelect(item.operator)
                }
            }}
            isItemEqualToValue={(a, b) => a?.id === b?.id}
            itemToStringLabel={(item) => item?.label ?? ''}
            itemToStringValue={(item) => item?.id ?? ''}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            open
            onOpenChange={(open) => {
                if (!open && !selectedRef.current) {
                    onDismiss()
                }
                selectedRef.current = false
            }}
            autoHighlight
        >
            <Combobox.Input
                ref={inputRef}
                aria-label="Change operator"
                placeholder="Operator..."
                className={`${CHIP_BASE} rounded-none min-w-[60px] max-w-[120px] focus:outline-none`}
            />
            <Combobox.Portal>
                <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4} align="start">
                    <Combobox.Popup className="primitive-menu-content min-w-[200px] flex flex-col max-h-[min(300px,var(--available-height))]">
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-px p-1">
                                {filteredItems.map((item) => {
                                    const isActive = currentItem?.id === item.id
                                    return (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            render={(props) => (
                                                <ButtonPrimitive
                                                    {...props}
                                                    menuItem
                                                    fullWidth
                                                    active={isActive}
                                                >
                                                    {isActive && (
                                                        <IconCheck className="size-4 text-success shrink-0" />
                                                    )}
                                                    <span className="truncate flex-1">{item.label}</span>
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )
                                })}
                            </Combobox.List>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}

// ── Inline Value Combobox (for editing completed chips) ──

function InlineValueCombobox({
    propertyKey,
    filterType,
    groupTypeIndex: _groupTypeIndex,
    currentValues,
    onCommit,
    onDismiss,
}: {
    propertyKey: string
    filterType: PropertyFilterType
    groupTypeIndex?: number
    currentValues: string[]
    onCommit: (val: PropertyFilterValue) => void
    onDismiss: () => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null!)
    const [searchValue, setSearchValue] = useState('')
    const [selectedValues, setSelectedValues] = useState<ValueComboboxItem[]>(
        currentValues.map((v) => ({ id: v, value: v, label: v }))
    )
    const justSelectedRef = useRef(false)
    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(filterType)

    useEffect(() => {
        loadPropertyValues({
            endpoint: undefined,
            type: propertyDefinitionType,
            newInput: '',
            propertyKey,
            eventNames: [],
        })
    }, [loadPropertyValues, propertyDefinitionType, propertyKey])

    useEffect(() => {
        if (searchValue) {
            loadPropertyValues({
                endpoint: undefined,
                type: propertyDefinitionType,
                newInput: searchValue,
                propertyKey,
                eventNames: [],
            })
        }
    }, [searchValue, loadPropertyValues, propertyDefinitionType, propertyKey])

    const valueItems = useMemo((): ValueComboboxItem[] => {
        const propValues = options[propertyKey]?.values || []
        return propValues.map((v: any) => ({
            id: String(v.name ?? v),
            value: String(v.name ?? v),
            label: String(v.name ?? v),
        }))
    }, [options, propertyKey])

    const filteredItems = useMemo(() => filterValueItems(valueItems, searchValue), [valueItems, searchValue])

    const selectedIds = useMemo(() => new Set(selectedValues.map((v) => v.value)), [selectedValues])

    const allItems = useMemo(() => {
        const alreadyExists =
            filteredItems.some((i) => i.value === searchValue) || selectedValues.some((i) => i.value === searchValue)
        if (searchValue && !alreadyExists) {
            return [{ id: `custom::${searchValue}`, value: searchValue, label: searchValue }, ...filteredItems]
        }
        return filteredItems
    }, [filteredItems, searchValue, selectedValues])

    const handleValueChange = useCallback((newValues: ValueComboboxItem[]) => {
        justSelectedRef.current = true
        setSelectedValues(newValues)
        setTimeout(() => {
            justSelectedRef.current = false
        }, 0)
    }, [])

    useEffect(() => {
        requestAnimationFrame(() => inputRef.current?.focus())
    }, [])

    return (
        <Combobox.Root
            multiple
            items={valueItems}
            filteredItems={allItems}
            filter={null}
            value={selectedValues}
            onValueChange={handleValueChange}
            isItemEqualToValue={(a, b) => a?.value === b?.value}
            itemToStringLabel={(item) => item?.label ?? ''}
            itemToStringValue={(item) => item?.id ?? ''}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            open
            onOpenChange={(open) => {
                if (!open && !justSelectedRef.current) {
                    if (selectedValues.length > 0) {
                        const values = selectedValues.map((v) => v.value)
                        onCommit(values.length === 1 ? values[0] : values)
                    } else {
                        onDismiss()
                    }
                }
            }}
            autoHighlight
        >
            <Combobox.Chips className="contents">
                <Combobox.Value>
                    {(values: ValueComboboxItem[]) =>
                        values.map((item, i) => (
                            <Combobox.Chip
                                key={item.id}
                                className={`${CHIP_BASE} ${valueChipRounding(i, values.length, true)} gap-0.5 cursor-default outline-none focus-visible:bg-fill-button-tertiary-active`}
                            >
                                {item.label}
                                <Combobox.ChipRemove
                                    className="inline-flex items-center justify-center size-3.5 rounded-sm hover:bg-fill-button-tertiary-hover cursor-pointer"
                                    aria-label={`Remove ${item.label}`}
                                >
                                    <IconX className="size-2.5 text-tertiary" />
                                </Combobox.ChipRemove>
                            </Combobox.Chip>
                        ))
                    }
                </Combobox.Value>
                <Combobox.Input
                    ref={inputRef}
                    aria-label="Change values"
                    placeholder={selectedValues.length === 0 ? 'Value...' : ''}
                    className="flex-1 min-w-[60px] px-1 py-0.5 text-sm focus:outline-none border-transparent bg-transparent"
                />
            </Combobox.Chips>
            <Combobox.Portal>
                <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4} align="start">
                    <Combobox.Popup className="primitive-menu-content min-w-[200px] flex flex-col max-h-[min(300px,var(--available-height))]">
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-px p-1">
                                {allItems.map((item) => {
                                    const isSelected = selectedIds.has(item.value)
                                    return (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            render={(props) => (
                                                <ButtonPrimitive {...props} menuItem fullWidth active={isSelected}>
                                                    {isSelected && (
                                                        <IconCheck className="size-4 text-success shrink-0" />
                                                    )}
                                                    <span className="truncate flex-1">
                                                        {item.id.startsWith('custom::')
                                                            ? `Create "${item.label}"`
                                                            : item.label}
                                                    </span>
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )
                                })}
                                {allItems.length === 0 && (
                                    <ButtonPrimitive fullWidth className="text-tertiary">
                                        {options[propertyKey]?.status === 'loading' ? (
                                            <span className="italic flex items-center gap-1">
                                                <Spinner size="small" /> Loading...
                                            </span>
                                        ) : (
                                            <span className="italic">Type a value</span>
                                        )}
                                    </ButtonPrimitive>
                                )}
                            </Combobox.List>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}
