import { Combobox } from '@base-ui/react/combobox'
import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconSearch, IconX } from '@posthog/icons'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { taxonomicFilterTypeToPropertyFilterType } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { isInsightVizNode, isRetentionQuery } from '~/queries/utils'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import {
    BreakdownComboboxGroup,
    BreakdownComboboxItem,
    TaxonomicBreakdownComboboxLogicProps,
    taxonomicBreakdownComboboxLogic,
} from './taxonomicBreakdownComboboxLogic'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

interface TaxonomicBreakdownComboboxProps {
    insightProps: InsightLogicProps
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    disabledReason?: string
    updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => void
    updateDisplay: (display: ChartDisplayType | undefined) => void
    disablePropertyInfo?: boolean
    size?: 'small' | 'medium'
}

export function TaxonomicBreakdownCombobox({
    insightProps,
    isTrends,
    disabledReason,
    disablePropertyInfo,
    size = 'medium',
}: TaxonomicBreakdownComboboxProps): JSX.Element {
    const { allEventNames, query } = useValues(insightVizDataLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { breakdownArray, isAddBreakdownDisabled, includeSessions, currentDataWarehouseSchemaColumns } =
        useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown, removeBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    const inputRef = useRef<HTMLInputElement>(null!)

    let taxonomicGroupTypes: TaxonomicFilterGroupType[]
    if (isRetentionQuery(query) || (isInsightVizNode(query) && isRetentionQuery(query.source))) {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
        ]
    } else {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.EventFeatureFlags,
            TaxonomicFilterGroupType.EventMetadata,
            ...groupsTaxonomicTypes,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
            ...(includeSessions ? [TaxonomicFilterGroupType.SessionProperties] : []),
            TaxonomicFilterGroupType.HogQLExpression,
            TaxonomicFilterGroupType.DataWarehouseProperties,
            TaxonomicFilterGroupType.DataWarehousePersonProperties,
        ]
    }

    const taxonomicFilterLogicKey = `taxonomicBreakdownCombobox-${insightProps.dashboardItemId || 'new'}`

    const comboboxLogicProps: TaxonomicBreakdownComboboxLogicProps = {
        insightProps,
        taxonomicGroupTypes,
        eventNames: allEventNames,
        schemaColumns: currentDataWarehouseSchemaColumns,
        taxonomicFilterLogicKey,
    }

    return (
        <BindLogic logic={taxonomicBreakdownComboboxLogic} props={comboboxLogicProps}>
            <TaxonomicBreakdownComboboxInner
                insightProps={insightProps}
                isTrends={isTrends}
                disabledReason={disabledReason}
                disablePropertyInfo={disablePropertyInfo}
                size={size}
                inputRef={inputRef}
                breakdownArray={breakdownArray}
                isAddBreakdownDisabled={isAddBreakdownDisabled}
                addBreakdown={addBreakdown}
                removeBreakdown={removeBreakdown}
            />
        </BindLogic>
    )
}

interface TaxonomicBreakdownComboboxInnerProps {
    insightProps: InsightLogicProps
    isTrends: boolean
    disabledReason?: string
    disablePropertyInfo?: boolean
    size: 'small' | 'medium'
    inputRef: React.RefObject<HTMLInputElement>
    breakdownArray: any[]
    isAddBreakdownDisabled: boolean
    addBreakdown: (value: any, group: any) => void
    removeBreakdown: (value: string | number, type: string) => void
}

/** Filter groups by search text. Remote groups are already API-filtered; local groups use simple string match. */
function filterGroups(groups: BreakdownComboboxGroup[], search: string): BreakdownComboboxGroup[] {
    if (!search) {
        return groups
    }
    const lower = search.toLowerCase()
    return groups
        .map((group) => ({
            ...group,
            // Remote groups: API already returned search-filtered results, show as-is
            // Local groups: filter by display name
            items: group.isRemote ? group.items : group.items.filter((item) => item.name.toLowerCase().includes(lower)),
        }))
        .filter((g) => g.items.length > 0)
}

function TaxonomicBreakdownComboboxInner({
    disabledReason,
    disablePropertyInfo,
    inputRef,
    breakdownArray,
    isAddBreakdownDisabled,
    addBreakdown,
    removeBreakdown,
}: TaxonomicBreakdownComboboxInnerProps): JSX.Element {
    const { rawGroupedItems, hasHogQLGroup, remoteResultsLoading } = useValues(taxonomicBreakdownComboboxLogic)
    const { setSearchQuery, loadRemoteResults } = useActions(taxonomicBreakdownComboboxLogic)

    const [searchValue, setSearchValue] = useState('')
    const [open, setOpen] = useState(false)
    const hasLoadedRemote = useRef(false)

    // Trigger remote load on first open
    useEffect(() => {
        if (open && !hasLoadedRemote.current) {
            hasLoadedRemote.current = true
            loadRemoteResults({})
        }
    }, [open, loadRemoteResults])

    // Sync search to kea for remote API calls
    useEffect(() => {
        setSearchQuery(searchValue)
    }, [searchValue, setSearchQuery])

    // Frontend filtering: local groups filtered by display name, remote groups shown as-is
    const filteredGroups = useMemo(() => filterGroups(rawGroupedItems, searchValue), [rawGroupedItems, searchValue])
    const filteredItems = useMemo(() => filteredGroups.flatMap((g) => g.items), [filteredGroups])

    // Track which breakdowns are currently selected
    const selectedBreakdownIds = useMemo(() => {
        const ids = new Set<string>()
        for (const breakdown of breakdownArray) {
            if (typeof breakdown === 'object' && breakdown.property != null) {
                ids.add(`${breakdown.type || 'event'}::${breakdown.property}`)
            } else if (breakdown != null) {
                ids.add(String(breakdown))
            }
        }
        return ids
    }, [breakdownArray])

    // Map breakdownArray to BreakdownComboboxItem[] for base-ui's value prop
    const selectedItems = useMemo(() => {
        const items: BreakdownComboboxItem[] = []
        for (const breakdown of breakdownArray) {
            const id =
                typeof breakdown === 'object' && breakdown.property != null
                    ? `${breakdown.type || 'event'}::${breakdown.property}`
                    : `event::${breakdown}`
            const found =
                filteredItems.find((i) => i.id === id) ||
                rawGroupedItems.flatMap((g) => g.items).find((i) => i.id === id)
            if (found) {
                items.push(found)
            }
        }
        return items
    }, [breakdownArray, filteredItems, rawGroupedItems])

    const handleValueChange = useCallback(
        (newValues: BreakdownComboboxItem[]) => {
            const newIds = new Set(newValues.map((v) => v.id))
            const oldIds = new Set(selectedItems.map((v) => v.id))

            // Added items
            for (const item of newValues) {
                if (!oldIds.has(item.id)) {
                    addBreakdown(item.value, item.taxonomicGroup)
                }
            }
            // Removed items
            for (const item of selectedItems) {
                if (!newIds.has(item.id)) {
                    const breakdownType = taxonomicFilterTypeToPropertyFilterType(item.taxonomicGroup.type) || 'event'
                    removeBreakdown(item.value as string | number, breakdownType)
                }
            }

            setSearchValue('')
            inputRef.current?.focus()
        },
        [selectedItems, addBreakdown, removeBreakdown, inputRef]
    )

    const handleHogQLSubmit = useCallback(
        (value: string | number | null) => {
            if (!value) {
                return
            }
            addBreakdown(value, {
                type: TaxonomicFilterGroupType.HogQLExpression,
                name: 'SQL expression',
                searchPlaceholder: null,
                getPopoverHeader: () => 'SQL expression',
            })
        },
        [addBreakdown]
    )

    return (
        <Combobox.Root
            multiple
            items={filteredItems}
            value={selectedItems}
            onValueChange={handleValueChange}
            isItemEqualToValue={(a, b) => a.id === b.id}
            itemToStringValue={(item) => item.name}
            open={open}
            onOpenChange={setOpen}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            filter={() => true}
            autoHighlight
        >
            <div className="flex flex-col gap-2">
                <div
                    className="group input-like flex gap-1 items-center flex-wrap relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2 cursor-text"
                    onClick={() => {
                        if (!disabledReason) {
                            setOpen(true)
                            inputRef.current?.focus()
                        }
                    }}
                >
                    <IconSearch className="size-4 text-tertiary shrink-0" />

                    {/* Chips for selected breakdowns */}
                    {selectedItems.map((item) => (
                        <span
                            key={item.id}
                            className="inline-flex items-center gap-0.5 bg-fill-button-tertiary rounded-sm px-1.5 py-0.5 text-xs font-medium max-w-[200px]"
                        >
                            <span className="truncate">
                                <PropertyKeyInfo
                                    value={item.name}
                                    disablePopover={disablePropertyInfo}
                                    type={item.groupType}
                                />
                            </span>
                            <ButtonPrimitive
                                iconOnly
                                size="xs"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    const breakdownType =
                                        taxonomicFilterTypeToPropertyFilterType(item.taxonomicGroup.type) || 'event'
                                    removeBreakdown(item.value as string | number, breakdownType)
                                }}
                                aria-label="Remove breakdown"
                                className="p-0"
                            >
                                <IconX className="size-3 text-tertiary" />
                            </ButtonPrimitive>
                        </span>
                    ))}

                    {/* Render plain chips for breakdowns not found in the items list */}
                    {breakdownArray.map((breakdown) => {
                        const id =
                            typeof breakdown === 'object' && breakdown.property != null
                                ? `${breakdown.type || 'event'}::${breakdown.property}`
                                : `event::${breakdown}`
                        if (selectedItems.find((i) => i.id === id)) {
                            return null // Already rendered above
                        }
                        const displayValue =
                            typeof breakdown === 'object' ? String(breakdown.property) : String(breakdown)
                        const breakdownType = typeof breakdown === 'object' ? breakdown.type || 'event' : 'event'
                        return (
                            <span
                                key={id}
                                className="inline-flex items-center gap-0.5 bg-fill-button-tertiary rounded-sm px-1.5 py-0.5 text-xs font-medium max-w-[200px]"
                            >
                                <span className="truncate">{displayValue}</span>
                                <ButtonPrimitive
                                    iconOnly
                                    size="xs"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        removeBreakdown(
                                            typeof breakdown === 'object' ? breakdown.property : breakdown,
                                            breakdownType
                                        )
                                    }}
                                    aria-label="Remove breakdown"
                                    className="p-0"
                                >
                                    <IconX className="size-3 text-tertiary" />
                                </ButtonPrimitive>
                            </span>
                        )
                    })}

                    {!isAddBreakdownDisabled && (
                        <Combobox.Input
                            ref={inputRef}
                            aria-label="Search breakdown properties"
                            placeholder={breakdownArray.length === 0 ? 'Add breakdown...' : ''}
                            className="flex-1 min-w-[80px] px-1 py-0.5 text-sm focus:outline-none border-transparent bg-transparent"
                            disabled={!!disabledReason}
                        />
                    )}
                </div>

                <Combobox.Portal>
                    <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4}>
                        <Combobox.Popup className="primitive-menu-content min-w-[300px] max-w-[400px] flex flex-col max-h-[min(400px,var(--available-height))]">
                            <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                                <Combobox.List className="flex flex-col gap-px p-1">
                                    {filteredGroups.map((group) => (
                                        <Combobox.Group
                                            key={group.type}
                                            items={group.items}
                                            className="flex flex-col gap-px"
                                        >
                                            <Combobox.GroupLabel className="px-2 py-1 sticky top-0 bg-surface-primary z-1">
                                                <Label intent="menu">{group.name}</Label>
                                            </Combobox.GroupLabel>
                                            <Combobox.Collection>
                                                {(item: BreakdownComboboxItem) => {
                                                    const isSelected =
                                                        selectedBreakdownIds.has(item.id) ||
                                                        selectedBreakdownIds.has(String(item.value))
                                                    const isAtLimit = isAddBreakdownDisabled && !isSelected
                                                    return (
                                                        <Combobox.Item
                                                            key={item.id}
                                                            value={item}
                                                            disabled={isAtLimit}
                                                            render={(props) => (
                                                                <ButtonPrimitive
                                                                    {...props}
                                                                    menuItem
                                                                    fullWidth
                                                                    active={isSelected}
                                                                    disabled={isAtLimit}
                                                                >
                                                                    {isSelected ? (
                                                                        <IconCheck className="size-4 text-success shrink-0" />
                                                                    ) : (
                                                                        item.icon && (
                                                                            <span className="shrink-0">
                                                                                {item.icon}
                                                                            </span>
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
                                                }}
                                            </Combobox.Collection>
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
                                                onChange={handleHogQLSubmit}
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
            </div>
        </Combobox.Root>
    )
}
