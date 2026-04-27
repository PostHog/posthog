import '../../lemon-ui/Popover/Popover.scss'
import './InfiniteList.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { CSSProperties, useEffect, useState } from 'react'
import { List, useListRef } from 'react-window'

import { IconArchive, IconCheck, IconPin, IconPinFilled, IconPlus, IconSearch } from '@posthog/icons'
import { LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { ControlledDefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { AUTOCAPTURE_INTERACTIONS } from 'lib/components/TaxonomicFilter/eventTypeShortcuts'
import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    DataWarehousePopoverField,
    DefinitionPopoverRenderer,
    isQuickFilterItem,
    isSkeletonItem,
    QuickFilterItem,
    SkeletonItem,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterGroupValueMap,
} from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { isDefinitionStale } from 'lib/utils/definitions'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { EventDefinition, PropertyDefinition } from '~/types'

import { NO_ITEM_SELECTED, infiniteListLogic } from './infiniteListLogic'

export interface InfiniteListProps {
    popupAnchorElement: HTMLDivElement | null
    definitionPopoverRenderer?: DefinitionPopoverRenderer
}

function hasLocalListContext(item: unknown): boolean {
    return hasRecentContext(item) || hasPinnedContext(item)
}

function quickFilterPopoverContents(item: QuickFilterItem): JSX.Element {
    const label = AUTOCAPTURE_INTERACTIONS.find((i) => i.eventType === item.filterValue)?.label ?? item.filterValue
    const verbLower = label.toLowerCase()
    const description = item.eventName
        ? `Autocapture event filtered by ${verbLower} event type`
        : `${label} event type filter`
    return (
        <div className="p-3">
            <div className="text-sm">{description}</div>
            <LemonDivider />
            <div className="text-xs text-secondary">
                Adds {item.eventName ? <code>{item.eventName}</code> : 'a property filter'} with{' '}
                <code>
                    {item.propertyKey} = {item.filterValue}
                </code>
            </div>
        </div>
    )
}

function getSourceGroupType(item: TaxonomicDefinitionTypes): TaxonomicFilterGroupType | undefined {
    if (hasRecentContext(item)) {
        return item._recentContext.sourceGroupType
    }
    if (hasPinnedContext(item)) {
        return item._pinnedContext.sourceGroupType
    }
    return undefined
}

function getLocalListLabel(item: TaxonomicDefinitionTypes): string | undefined {
    if (hasRecentContext(item)) {
        return 'recent'
    }
    if (hasPinnedContext(item)) {
        return 'pinned'
    }
    return undefined
}

const staleIndicator = (parsedLastSeen: dayjs.Dayjs | null): JSX.Element => {
    return (
        <Tooltip
            title={
                <>
                    This event was last seen <b>{parsedLastSeen ? parsedLastSeen.fromNow() : 'a while ago'}</b>.
                </>
            }
        >
            <LemonTag>Stale</LemonTag>
        </Tooltip>
    )
}

const unusedIndicator = (eventNames: string[]): JSX.Element => {
    return (
        <Tooltip
            title={
                <>
                    This property has not been seen on{' '}
                    <span>
                        {eventNames ? (
                            <>
                                the event{eventNames.length > 1 ? 's' : ''}{' '}
                                {eventNames.map((e, index) => (
                                    <>
                                        {index === 0 ? '' : index === eventNames.length - 1 ? ' and ' : ', '}
                                        <strong>"{e}"</strong>
                                    </>
                                ))}
                            </>
                        ) : (
                            'this event'
                        )}
                    </span>
                    , but has been seen on other events.
                </>
            }
        >
            <LemonTag>Not seen</LemonTag>
        </Tooltip>
    )
}

const renderItemContents = ({
    item,
    listGroupType,
    itemGroup,
    eventNames,
    isActive,
}: {
    item: TaxonomicDefinitionTypes
    listGroupType: TaxonomicFilterGroupType
    itemGroup: TaxonomicFilterGroup
    eventNames: string[]
    isActive: boolean
}): JSX.Element | string => {
    if (isQuickFilterItem(item)) {
        const icon = itemGroup.getIcon ? (
            <div className="taxonomic-list-row-contents-icon">{itemGroup.getIcon(item)}</div>
        ) : null
        return (
            <div
                className="taxonomic-list-row-contents min-w-0 flex items-center gap-2"
                data-attr={`taxonomic-shortcut-${item.filterValue}${item.eventName ? '-series' : '-property'}`}
            >
                {icon}
                <span className="truncate" title={item.name}>
                    {item.name}
                </span>
            </div>
        )
    }
    if (hasLocalListContext(item)) {
        const icon = isActive ? (
            <div className="taxonomic-list-row-contents-icon">
                <IconCheck />
            </div>
        ) : itemGroup.getIcon ? (
            <div className="taxonomic-list-row-contents-icon">{itemGroup.getIcon(item)}</div>
        ) : null

        if (hasRecentContext(item) && item._recentContext.propertyFilter) {
            const label = formatPropertyLabel(item._recentContext.propertyFilter, {})
            return (
                <div className="taxonomic-list-row-contents min-w-0">
                    {icon}
                    <span className="truncate" title={label}>
                        {label}
                    </span>
                </div>
            )
        }
        const coreDef = getCoreFilterDefinition(item.name, itemGroup.type)
        const label = coreDef?.label || item.name || ''
        return (
            <div className="taxonomic-list-row-contents min-w-0">
                {icon}
                <span className="truncate" title={label}>
                    {label}
                </span>
            </div>
        )
    }

    const parsedLastSeen = (item as EventDefinition).last_seen_at ? dayjs((item as EventDefinition).last_seen_at) : null
    const isStale =
        listGroupType === TaxonomicFilterGroupType.Events && 'id' in item && isDefinitionStale(item as EventDefinition)

    const isUnusedEventProperty =
        (listGroupType === TaxonomicFilterGroupType.NumericalEventProperties ||
            listGroupType === TaxonomicFilterGroupType.EventProperties ||
            listGroupType === TaxonomicFilterGroupType.EventFeatureFlags) &&
        (item as PropertyDefinition).is_seen_on_filtered_events !== null &&
        !(item as PropertyDefinition).is_seen_on_filtered_events

    const icon = isActive ? (
        <div className="taxonomic-list-row-contents-icon">
            <IconCheck />
        </div>
    ) : itemGroup.getIcon ? (
        <div className="taxonomic-list-row-contents-icon">{itemGroup.getIcon(item)}</div>
    ) : null

    return listGroupType === TaxonomicFilterGroupType.EventProperties ||
        listGroupType === TaxonomicFilterGroupType.EventFeatureFlags ||
        listGroupType === TaxonomicFilterGroupType.NumericalEventProperties ||
        listGroupType === TaxonomicFilterGroupType.PersonProperties ||
        listGroupType === TaxonomicFilterGroupType.Events ||
        listGroupType === TaxonomicFilterGroupType.CustomEvents ||
        listGroupType === TaxonomicFilterGroupType.Metadata ||
        listGroupType === TaxonomicFilterGroupType.SessionProperties ||
        listGroupType === TaxonomicFilterGroupType.MaxAIContext ||
        listGroupType === TaxonomicFilterGroupType.ErrorTrackingProperties ||
        listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix) ? (
        <>
            <div className={clsx('taxonomic-list-row-contents', isStale && 'text-muted')}>
                {icon}
                <PropertyKeyInfo
                    value={item.name ?? ''}
                    disablePopover
                    disableIcon
                    className="w-full"
                    type={itemGroup.type}
                />
            </div>
            {isStale && staleIndicator(parsedLastSeen)}
            {isUnusedEventProperty && unusedIndicator(eventNames)}
        </>
    ) : (
        <div className="taxonomic-list-row-contents min-w-0">
            {listGroupType === TaxonomicFilterGroupType.Elements ? (
                <PropertyKeyInfo value={item.name ?? ''} disablePopover className="w-full" type={listGroupType} />
            ) : (
                <>
                    {icon}
                    <span className="truncate" title={itemGroup.getName?.(item) || item.name || ''}>
                        {itemGroup.getName?.(item) || item.name || ''}
                    </span>
                </>
            )}
        </div>
    )
}

const selectedItemHasPopover = (
    item?: TaxonomicDefinitionTypes,
    group?: TaxonomicFilterGroup,
    taxonomicGroups?: TaxonomicFilterGroup[]
): boolean => {
    if (!item || !group) {
        return false
    }

    const sourceGroupType = getSourceGroupType(item)
    if (sourceGroupType) {
        const sourceGroup = taxonomicGroups?.find((g) => g.type === sourceGroupType)
        return !!sourceGroup && !sourceGroup.isMetaGroup
    }

    return !!group.getValue?.(item) && !group.isMetaGroup
}

const canSelectItem = (
    listGroupType?: TaxonomicFilterGroupType,
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
): boolean => {
    return (
        !!listGroupType &&
        (dataWarehousePopoverFields?.length === 0 || listGroupType !== TaxonomicFilterGroupType.DataWarehouse)
    )
}

interface InfiniteListRowProps {
    results: (TaxonomicDefinitionTypes | SkeletonItem)[]
    taxonomicGroups: TaxonomicFilterGroup[]
    group: TaxonomicFilterGroup
    listGroupType: TaxonomicFilterGroupType
    groupType: TaxonomicFilterGroupType | undefined
    value: string | number | null | undefined
    selectedProperties: TaxonomicFilterGroupValueMap
    eventNames: string[]
    highlightedIndex: number
    isActiveTab: boolean
    mouseInteractionsEnabled: boolean
    showPopover: boolean
    totalListCount: number
    totalResultCount: number
    expandedCount: number
    isExpandable: boolean
    isLoading: boolean
    showNonCapturedEventOption: boolean
    trimmedSearchQuery: string
    dataWarehousePopoverFields: DataWarehousePopoverField[] | undefined
    popupAnchorElement: HTMLDivElement | null
    showSuggestedFiltersEmptyState: boolean
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    setIndex: (index: number) => void
    pinnedRowIndex: number | null
    onToggleRowPin: (rowIndex: number) => void
    expand: () => void
    selectItem: (
        group: TaxonomicFilterGroup,
        value: string | number | null,
        item: TaxonomicDefinitionTypes | { name: string; isNonCaptured: true }
    ) => void
    setHighlightedItemElement: (element: HTMLDivElement | null) => void
}

function InfiniteListSkeletonItem({
    style,
    listGroupType,
    rowIndex,
    groupName,
}: {
    style: CSSProperties
    listGroupType: TaxonomicFilterGroupType
    rowIndex: number
    groupName: string
}): JSX.Element {
    return (
        <div
            className={clsx('taxonomic-list-row', 'skeleton-row')}
            style={style}
            data-attr={`prop-skeleton-${listGroupType}-${rowIndex}`}
        >
            <div className="taxonomic-list-row-contents w-full">
                <LemonSkeleton className="h-4 flex-1" />
                <LemonTag size="small" type="highlight" className="ml-2 shrink-0">
                    {groupName}
                </LemonTag>
            </div>
        </div>
    )
}

export const InfiniteListRow = ({
    index: rowIndex,
    style,
    results,
    taxonomicGroups,
    group,
    listGroupType,
    groupType,
    value,
    selectedProperties,
    eventNames,
    highlightedIndex,
    isActiveTab,
    mouseInteractionsEnabled,
    showPopover,
    totalListCount,
    totalResultCount,
    expandedCount,
    isExpandable,
    isLoading,
    showNonCapturedEventOption,
    trimmedSearchQuery,
    dataWarehousePopoverFields,
    popupAnchorElement,
    showSuggestedFiltersEmptyState,
    taxonomicGroupTypes,
    setIndex,
    pinnedRowIndex,
    onToggleRowPin,
    expand,
    selectItem,
    setHighlightedItemElement,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & InfiniteListRowProps): JSX.Element | null => {
    if (showSuggestedFiltersEmptyState && rowIndex === results.length) {
        return (
            <div style={style} className="flex flex-col items-center justify-center gap-1 pt-2">
                <IconSearch className="text-3xl text-tertiary" />
                <span className="text-secondary text-center text-xs">Start searching and we'll suggest filters...</span>
                <SuggestedFiltersSearchHint taxonomicGroupTypes={taxonomicGroupTypes} />
            </div>
        )
    }

    const item = results[rowIndex]

    if (isSkeletonItem(item)) {
        return (
            <InfiniteListSkeletonItem
                style={style}
                listGroupType={listGroupType}
                rowIndex={rowIndex}
                groupName={item.groupName}
            />
        )
    }

    const itemGroup = getItemGroup(item, taxonomicGroups, group)
    const itemValue = item ? itemGroup?.getValue?.(item) : null

    const normalizedValue = typeof itemValue === 'number' && typeof value === 'string' ? Number(value) : value

    const isSelected = listGroupType === groupType && itemValue === normalizedValue

    const isHighlighted = rowIndex === highlightedIndex && isActiveTab

    const isActive = itemValue ? !!selectedProperties[listGroupType]?.includes(itemValue) : false

    if (showNonCapturedEventOption && rowIndex === 0) {
        const selectNonCapturedEvent = (): void => {
            selectItem(itemGroup, trimmedSearchQuery, { name: trimmedSearchQuery, isNonCaptured: true })
        }

        return (
            <LemonRow
                fullWidth
                style={style}
                className={clsx(
                    'taxonomic-list-row',
                    'border border-dashed border-secondary rounded min-h-9 justify-center'
                )}
                outlined={false}
                onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                        selectNonCapturedEvent()
                    }
                }}
                onClick={selectNonCapturedEvent}
                onMouseEnter={() => mouseInteractionsEnabled && setIndex(rowIndex)}
                icon={<IconPlus className="text-muted size-4" />}
                data-attr="prop-filter-event-option-custom"
            >
                <div className="flex items-center gap-2">
                    <span className="text-muted">Select event:</span>
                    <span className="font-medium">{trimmedSearchQuery}</span>
                    <LemonTag type="caution" size="small">
                        Not seen yet
                    </LemonTag>
                </div>
            </LemonRow>
        )
    }

    const isPinnedToAnotherRow = pinnedRowIndex !== null && pinnedRowIndex !== rowIndex
    const isCurrentRowPinned = pinnedRowIndex === rowIndex

    const commonDivProps: React.HTMLProps<HTMLDivElement> = {
        className: clsx(
            'taxonomic-list-row',
            rowIndex === highlightedIndex && mouseInteractionsEnabled && 'hover',
            isCurrentRowPinned && 'active',
            isActive && 'active',
            isSelected && 'selected'
        ),
        onMouseOver: () => {
            if (!mouseInteractionsEnabled) {
                setIndex(NO_ITEM_SELECTED)
                return
            }
            if (isPinnedToAnotherRow) {
                return
            }
            setIndex(rowIndex)
        },
        onMouseLeave: () =>
            mouseInteractionsEnabled && !showPopover && !isPinnedToAnotherRow ? setIndex(NO_ITEM_SELECTED) : null,
        style: style,
        ref: isHighlighted
            ? (element) => {
                  setHighlightedItemElement(element && popupAnchorElement ? popupAnchorElement : element)
              }
            : null,
    }

    if (item && itemGroup) {
        const isDisabledItem = itemGroup?.getIsDisabled?.(item) ?? false
        const isPinnable = !canSelectItem(listGroupType, dataWarehousePopoverFields) && !isDisabledItem
        const isCrossGroupItem = !!group.isLocalOnly && itemGroup.type !== listGroupType
        const localListLabel = getLocalListLabel(item)
        const localListGroup = hasLocalListContext(item)
            ? taxonomicGroups.find((g) => g.type === listGroupType)
            : undefined
        const shouldShowPinIcon = isPinnable && (isHighlighted || isCurrentRowPinned)
        const pinIcon = isCurrentRowPinned ? (
            <IconPinFilled className="size-4 text-warning" />
        ) : (
            <IconPin className="size-4 text-secondary" />
        )

        const { listGroupType: resolvedListGroupType, itemGroup: resolvedItemGroup } = resolveItemRendering({
            item,
            itemGroup,
            listGroupType,
            isCrossGroupItem,
            localListGroup,
            fallbackGroup: group,
        })

        return (
            <div
                {...commonDivProps}
                className={clsx(commonDivProps.className, isDisabledItem && 'cursor-not-allowed opacity-60')}
                data-attr={`prop-filter-${listGroupType}-${rowIndex}`}
                data-ph-capture-attribute-taxonomic-group={resolvedListGroupType}
                data-ph-capture-attribute-taxonomic-group-name={resolvedItemGroup.name}
                role="option"
                aria-selected={isSelected}
                aria-disabled={isDisabledItem}
                onClick={(event) => {
                    if (isDisabledItem) {
                        event.preventDefault()
                        event.stopPropagation()
                        return
                    }
                    if (canSelectItem(listGroupType, dataWarehousePopoverFields)) {
                        return selectItem(itemGroup, itemValue ?? null, item)
                    }
                    onToggleRowPin(rowIndex)
                }}
            >
                {renderItemContents({
                    item,
                    listGroupType: resolvedListGroupType,
                    itemGroup: resolvedItemGroup,
                    eventNames,
                    isActive,
                })}
                {isCrossGroupItem && (
                    <LemonTag size="small" type="highlight">
                        {localListLabel ? `${itemGroup.name} - ${localListLabel}` : itemGroup.name}
                    </LemonTag>
                )}
                {isPinnable && (
                    <div
                        className="taxonomic-list-row-pin"
                        data-attr={`pin-row-${listGroupType}-${rowIndex}`}
                        aria-hidden="true"
                    >
                        {shouldShowPinIcon ? pinIcon : null}
                    </div>
                )}
            </div>
        )
    }

    const isExpandRow = !item && rowIndex === totalListCount - 1 && isExpandable && !isLoading
    if (isExpandRow) {
        return (
            <div
                {...commonDivProps}
                className={clsx(commonDivProps.className, 'expand-row')}
                data-attr={`expand-list-${listGroupType}`}
                role="button"
                aria-label="Show more items"
                onClick={expand}
            >
                {group.expandLabel?.({ count: totalResultCount, expandedCount }) ??
                    `See ${expandedCount - totalResultCount} more ${pluralize(
                        expandedCount - totalResultCount,
                        'row',
                        'rows',
                        false
                    )}`}
            </div>
        )
    }

    return (
        <div
            {...commonDivProps}
            className={clsx(commonDivProps.className, 'skeleton-row')}
            data-attr={`prop-skeleton-${listGroupType}-${rowIndex}`}
        >
            <div className="taxonomic-list-row-contents">
                <div className="taxonomic-list-row-contents-icon">
                    <Spinner className="h-4 w-4" speed="0.8s" />
                </div>
                <LemonSkeleton className="h-4 flex-1" />
            </div>
        </div>
    )
}

function InfiniteListEmptyState(): JSX.Element {
    const { searchQuery, taxonomicGroupTypes } = useValues(taxonomicFilterLogic)

    const { group, needsMoreSearchCharacters, minSearchQueryLength, isSuggestedFilters } = useValues(infiniteListLogic)

    const emptySearchQuery = searchQuery.trim().length === 0
    const suggestedFiltersBeforeSearching = isSuggestedFilters && emptySearchQuery
    return (
        <div className="no-infinite-results flex flex-col gap-y-1 items-center">
            {suggestedFiltersBeforeSearching ? (
                <>
                    <IconSearch className="text-5xl text-tertiary" />
                    <span className="text-secondary text-center">Start searching and we'll suggest filters...</span>
                    <SuggestedFiltersSearchHint taxonomicGroupTypes={taxonomicGroupTypes} />
                </>
            ) : needsMoreSearchCharacters ? (
                <>
                    <IconSearch className="text-5xl text-tertiary" />
                    <span className="text-secondary text-center">
                        Search for{' '}
                        {group?.searchDescription || group?.searchPlaceholder || group?.name?.toLowerCase() || 'items'}
                    </span>
                    <span className="text-center text-secondary italic">
                        Type at least {minSearchQueryLength} characters to search
                    </span>
                </>
            ) : (
                <>
                    <IconArchive className="text-5xl text-tertiary" />
                    <span>
                        {emptySearchQuery ? (
                            'Start typing to find results'
                        ) : (
                            <>
                                No results for "<strong>{searchQuery}</strong>"
                            </>
                        )}
                    </span>
                </>
            )}
        </div>
    )
}

export function InfiniteList({ popupAnchorElement, definitionPopoverRenderer }: InfiniteListProps): JSX.Element {
    const {
        mouseInteractionsEnabled,
        eventNames,
        groupType,
        value,
        taxonomicGroups,
        taxonomicGroupTypes,
        selectedProperties,
        selectedItemMeta,
        dataWarehousePopoverFields,
    } = useValues(taxonomicFilterLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)
    const {
        isLoading,
        results,
        index,
        listGroupType,
        group,
        selectedItem,
        selectedItemInView,
        isExpandable,
        totalResultCount,
        totalListCount,
        expandedCount,
        showPopover,
        showNonCapturedEventOption,
        showEmptyState,
        showLoadingState,
        isSuggestedFilters,
        isActiveTab,
        rowCount,
        pinnedRowIndex,
        trimmedSearchQuery,
        showSuggestedFiltersEmptyState,
    } = useValues(infiniteListLogic)
    const { onRowsRendered, setIndex, togglePinnedRow, expand, updateRemoteItem } = useActions(infiniteListLogic)
    const [highlightedItemElement, setHighlightedItemElement] = useState<HTMLDivElement | null>(null)
    const listRef = useListRef(null)

    useEffect(() => {
        if (index >= 0 && listRef.current) {
            listRef.current.scrollToRow({ index, align: 'smart' })
        }
    }, [index, listRef])

    const selectedItemGroup = getItemGroup(selectedItem, taxonomicGroups, group)
    const selectedItemIsRecent = selectedItem ? hasRecentContext(selectedItem) : false
    const selectedItemIsQuickFilter = selectedItem ? isQuickFilterItem(selectedItem) : false

    return (
        <div
            className={cn(
                'taxonomic-infinite-list',
                showEmptyState && 'empty-infinite-list',
                'h-full',
                isSuggestedFilters && 'empty-infinite-list--start'
            )}
        >
            {showEmptyState ? (
                <InfiniteListEmptyState />
            ) : showLoadingState ? (
                <div className="flex items-center justify-center h-full">
                    <Spinner className="text-3xl" />
                </div>
            ) : (
                <AutoSizer
                    renderProp={({ height, width }) =>
                        height && width ? (
                            <List<InfiniteListRowProps>
                                listRef={listRef}
                                style={{ width, height }}
                                rowCount={rowCount}
                                overscanCount={100}
                                rowHeight={(i) => (showSuggestedFiltersEmptyState && i === results.length ? 80 : 36)}
                                rowComponent={InfiniteListRow}
                                rowProps={{
                                    results,
                                    taxonomicGroups,
                                    group,
                                    listGroupType,
                                    groupType,
                                    value,
                                    selectedProperties,
                                    eventNames,
                                    highlightedIndex: index,
                                    isActiveTab,
                                    mouseInteractionsEnabled,
                                    showPopover,
                                    totalListCount,
                                    totalResultCount,
                                    expandedCount,
                                    isExpandable,
                                    isLoading,
                                    showNonCapturedEventOption,
                                    trimmedSearchQuery,
                                    dataWarehousePopoverFields,
                                    popupAnchorElement,
                                    showSuggestedFiltersEmptyState,
                                    taxonomicGroupTypes,
                                    setIndex,
                                    pinnedRowIndex,
                                    onToggleRowPin: togglePinnedRow,
                                    expand,
                                    selectItem,
                                    setHighlightedItemElement,
                                }}
                                onRowsRendered={(visibleRows, allRows) =>
                                    onRowsRendered({
                                        startIndex: visibleRows.startIndex,
                                        stopIndex: visibleRows.stopIndex,
                                        overscanStopIndex: allRows.stopIndex,
                                    })
                                }
                            />
                        ) : null
                    }
                />
            )}
            {isActiveTab &&
            selectedItemHasPopover(selectedItem, selectedItemGroup, taxonomicGroups) &&
            showPopover &&
            selectedItem ? (
                <BindLogic
                    logic={definitionPopoverLogic}
                    props={{
                        type: selectedItemGroup.type,
                        selectedItemMeta,
                        updateRemoteItem,
                    }}
                >
                    <ControlledDefinitionPopover
                        visible={selectedItemInView}
                        item={selectedItem}
                        group={selectedItemGroup}
                        highlightedItemElement={highlightedItemElement}
                        definitionPopoverRenderer={
                            selectedItemIsQuickFilter
                                ? ({ item }) => quickFilterPopoverContents(item as QuickFilterItem)
                                : selectedItemIsRecent
                                  ? ({ item, group, defaultView }) => {
                                        const recentRenderer = definitionPopoverRenderer
                                            ? definitionPopoverRenderer({ item, group, defaultView })
                                            : defaultView
                                        let label: string
                                        if (
                                            hasRecentContext(selectedItem) &&
                                            selectedItem._recentContext.propertyFilter
                                        ) {
                                            label = formatPropertyLabel(selectedItem._recentContext.propertyFilter, {})
                                        } else {
                                            const coreDef = getCoreFilterDefinition(
                                                selectedItem.name,
                                                selectedItemGroup?.type
                                            )
                                            label =
                                                coreDef?.label ||
                                                selectedItemGroup?.getName?.(selectedItem) ||
                                                selectedItem.name ||
                                                ''
                                        }
                                        return (
                                            <>
                                                <div className="p-3 pb-0">
                                                    <div className="text-xs font-semibold text-secondary uppercase">
                                                        Recent filter
                                                    </div>
                                                    <div className="text-sm mt-1">{label}</div>
                                                </div>
                                                <LemonDivider />
                                                {recentRenderer}
                                            </>
                                        )
                                    }
                                  : definitionPopoverRenderer
                        }
                    />
                </BindLogic>
            ) : null}
        </div>
    )
}

function SuggestedFiltersSearchHint({
    taxonomicGroupTypes,
}: {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
}): JSX.Element | null {
    const groupSet = new Set(taxonomicGroupTypes)
    const hints: string[] = []
    if (groupSet.has(TaxonomicFilterGroupType.EmailAddresses)) {
        hints.push('an email')
    }
    if (groupSet.has(TaxonomicFilterGroupType.PageviewUrls) || groupSet.has(TaxonomicFilterGroupType.PageviewEvents)) {
        hints.push('a URL')
    }
    if (groupSet.has(TaxonomicFilterGroupType.Screens) || groupSet.has(TaxonomicFilterGroupType.ScreenEvents)) {
        hints.push('a screen name')
    }
    if (hints.length === 0) {
        return null
    }
    const joined =
        hints.length === 1
            ? hints[0]
            : hints.length === 2
              ? `${hints[0]} or ${hints[1]}`
              : `${hints.slice(0, -1).join(', ')}, or ${hints[hints.length - 1]}`
    return <span className="text-center text-secondary italic">Try searching for {joined}</span>
}

function resolveItemRendering({
    item,
    itemGroup,
    listGroupType,
    isCrossGroupItem,
    localListGroup,
    fallbackGroup,
}: {
    item: TaxonomicDefinitionTypes
    itemGroup: TaxonomicFilterGroup
    listGroupType: TaxonomicFilterGroupType
    isCrossGroupItem: boolean
    localListGroup: TaxonomicFilterGroup | undefined
    fallbackGroup: TaxonomicFilterGroup
}): { listGroupType: TaxonomicFilterGroupType; itemGroup: TaxonomicFilterGroup } {
    const isRecentPropertyFilter = hasRecentContext(item) && item._recentContext.propertyFilter

    if (isRecentPropertyFilter) {
        return {
            listGroupType,
            itemGroup: localListGroup ?? fallbackGroup,
        }
    }

    if (hasLocalListContext(item) && !isCrossGroupItem) {
        return {
            listGroupType,
            itemGroup: localListGroup ?? fallbackGroup,
        }
    }

    if (isCrossGroupItem) {
        return {
            listGroupType: itemGroup.type,
            itemGroup,
        }
    }

    return { listGroupType, itemGroup }
}

export function getItemGroup(
    item: TaxonomicDefinitionTypes | undefined,
    groups: TaxonomicFilterGroup[],
    defaultGroup: TaxonomicFilterGroup
): TaxonomicFilterGroup {
    let group = defaultGroup

    const sourceType = item ? getSourceGroupType(item) : undefined
    if (sourceType) {
        const itemGroup = groups.find((g) => g.type === sourceType)
        if (itemGroup) {
            group = itemGroup
        }
    } else if (item && 'group' in item) {
        const itemGroup = groups.find((g) => item.group === g.type)
        if (itemGroup) {
            group = itemGroup
        }
    }

    return group
}
