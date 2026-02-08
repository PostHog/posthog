import { Combobox } from '@base-ui/react/combobox'
import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'

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
    disabledReason,
}: TaxonomicBreakdownComboboxProps): JSX.Element {
    const { allEventNames, query } = useValues(insightVizDataLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { breakdownArray, isAddBreakdownDisabled, includeSessions, currentDataWarehouseSchemaColumns } =
        useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown, removeBreakdown } = useActions(taxonomicBreakdownFilterLogic)

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
                disabledReason={disabledReason}
                breakdownArray={breakdownArray}
                isAddBreakdownDisabled={isAddBreakdownDisabled}
                addBreakdown={addBreakdown}
                removeBreakdown={removeBreakdown}
            />
        </BindLogic>
    )
}

interface TaxonomicBreakdownComboboxInnerProps {
    disabledReason?: string
    breakdownArray: any[]
    isAddBreakdownDisabled: boolean
    addBreakdown: (value: any, group: any) => void
    removeBreakdown: (value: string | number, type: string) => void
}

/** Client-side filter: match items by display name or value (case-insensitive contains). */
function filterGroups(groups: BreakdownComboboxGroup[], search: string): BreakdownComboboxGroup[] {
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

function TaxonomicBreakdownComboboxInner({
    disabledReason,
    breakdownArray,
    isAddBreakdownDisabled,
    addBreakdown,
    removeBreakdown,
}: TaxonomicBreakdownComboboxInnerProps): JSX.Element {
    const { rawGroupedItems, allRawItems, hasHogQLGroup, remoteResultsLoading } = useValues(
        taxonomicBreakdownComboboxLogic
    )
    const { loadRemoteResults } = useActions(taxonomicBreakdownComboboxLogic)

    const inputRef = useRef<HTMLInputElement>(null!)
    const hasLoadedRemote = useRef(false)
    const [searchValue, setSearchValue] = useState('')

    // Load data once on first open
    const handleOpenChange = useCallback(
        (open: boolean) => {
            if (open && !hasLoadedRemote.current) {
                hasLoadedRemote.current = true
                loadRemoteResults({})
            }
        },
        [loadRemoteResults]
    )

    // Client-side filtering only (no API re-fetch on search)
    const filteredGroups = useMemo(() => filterGroups(rawGroupedItems, searchValue), [rawGroupedItems, searchValue])
    const filteredItems = useMemo(() => filteredGroups.flatMap((g) => g.items), [filteredGroups])

    // Map breakdownArray → BreakdownComboboxItem[] for base-ui's controlled value.
    // Match by value since breakdownArray uses BreakdownType ('event') while
    // rawGroupedItems uses TaxonomicFilterGroupType ('event_properties').
    const selectedItems = useMemo(() => {
        const items: BreakdownComboboxItem[] = []
        for (const breakdown of breakdownArray) {
            const value = typeof breakdown === 'object' ? breakdown.property : breakdown
            const found = allRawItems.find((i) => i.value === value)
            if (found) {
                items.push(found)
            } else {
                const name = String(value)
                const groupType = TaxonomicFilterGroupType.EventProperties
                items.push({
                    id: `${groupType}::${value}`,
                    value,
                    name,
                    groupType,
                    taxonomicGroup: { type: groupType, name: '', searchPlaceholder: null, getPopoverHeader: () => '' },
                    isRemote: false,
                })
            }
        }
        return items
    }, [breakdownArray, allRawItems])

    // Track selected IDs for rendering checkmarks in the list
    const selectedIds = useMemo(() => new Set(selectedItems.map((i) => i.id)), [selectedItems])

    // Bridge base-ui's onValueChange to the breakdown add/remove actions
    const handleValueChange = useCallback(
        (newValues: BreakdownComboboxItem[]) => {
            const newIds = new Set(newValues.map((v) => v.id))
            const oldIds = new Set(selectedItems.map((v) => v.id))

            for (const item of newValues) {
                if (!oldIds.has(item.id)) {
                    addBreakdown(item.value, item.taxonomicGroup)
                }
            }
            for (const item of selectedItems) {
                if (!newIds.has(item.id)) {
                    const breakdownType = taxonomicFilterTypeToPropertyFilterType(item.taxonomicGroup.type) || 'event'
                    removeBreakdown(item.value as string | number, breakdownType)
                }
            }
        },
        [selectedItems, addBreakdown, removeBreakdown]
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
            items={allRawItems}
            filteredItems={filteredItems}
            filter={null}
            value={selectedItems}
            onValueChange={handleValueChange}
            isItemEqualToValue={(a, b) => a.id === b.id}
            itemToStringLabel={(item) => item.name}
            itemToStringValue={(item) => item.id}
            onOpenChange={handleOpenChange}
            inputValue={searchValue}
            onInputValueChange={setSearchValue}
            autoHighlight
        >
            {/* Input area with chips */}
            <div
                className="group input-like flex gap-1 items-center flex-wrap relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2 cursor-text"
                onClick={() => {
                    if (!disabledReason) {
                        inputRef.current?.focus()
                    }
                }}
            >
                <IconSearch className="size-4 text-tertiary shrink-0" />

                <Combobox.Chips className="contents">
                    <Combobox.Value>
                        {(value: BreakdownComboboxItem[]) =>
                            value.map((item) => (
                                <Combobox.Chip
                                    key={item.id}
                                    className="inline-flex items-center gap-0.5 bg-fill-button-tertiary rounded-sm px-1.5 py-0.5 text-xs font-medium max-w-[200px] cursor-default outline-none focus-visible:ring-1 focus-visible:ring-primary"
                                >
                                    <PropertyKeyInfo value={item.name} disablePopover type={item.groupType} />
                                    <Combobox.ChipRemove
                                        className="inline-flex items-center justify-center size-4 rounded-sm hover:bg-fill-button-tertiary-hover cursor-pointer"
                                        aria-label={`Remove ${item.name}`}
                                    >
                                        <IconX className="size-3 text-tertiary" />
                                    </Combobox.ChipRemove>
                                </Combobox.Chip>
                            ))
                        }
                    </Combobox.Value>

                    <Combobox.Input
                        ref={inputRef}
                        aria-label="Search breakdown properties"
                        placeholder={breakdownArray.length === 0 ? 'Add breakdown...' : ''}
                        className="flex-1 min-w-[80px] px-1 py-0.5 text-sm focus:outline-none border-transparent bg-transparent"
                        disabled={!!disabledReason}
                    />
                </Combobox.Chips>
            </div>

            {/* Dropdown popup */}
            <Combobox.Portal>
                <Combobox.Positioner className="z-[var(--z-popover)]" sideOffset={4}>
                    <Combobox.Popup className="primitive-menu-content min-w-[300px] flex flex-col max-h-[min(400px,var(--available-height))]">
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-px p-1">
                                {filteredGroups.map((group) => (
                                    <Combobox.Group key={group.type} className="flex flex-col gap-px">
                                        <Combobox.GroupLabel className="px-2 py-1 sticky top-0 bg-surface-primary z-1">
                                            <Label intent="menu">{group.name}</Label>
                                        </Combobox.GroupLabel>
                                        {group.items.map((item) => {
                                            const isSelected = selectedIds.has(item.id)
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
        </Combobox.Root>
    )
}
