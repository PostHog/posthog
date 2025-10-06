import '../../lemon-ui/Popover/Popover.scss'
import './InfiniteList.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'

import { IconArchive, IconCheck, IconPlus } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { ControlledDefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils'
import { isDefinitionStale } from 'lib/utils/definitions'

import { EventDefinition, PropertyDefinition } from '~/types'

import { NO_ITEM_SELECTED, infiniteListLogic } from './infiniteListLogic'

export interface InfiniteListProps {
    popupAnchorElement: HTMLDivElement | null
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
        <div className="taxonomic-list-row-contents">
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
    listGroupType?: TaxonomicFilterGroupType,
    group?: TaxonomicFilterGroup
): boolean => {
    // NB: also update "renderItemContents" above
    return (
        TaxonomicFilterGroupType.EventMetadata,
        !!item &&
            !!group?.getValue?.(item) &&
            !!listGroupType &&
            ([
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.Elements,
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.DataWarehouse,
                TaxonomicFilterGroupType.DataWarehouseProperties,
                TaxonomicFilterGroupType.DataWarehousePersonProperties,
                TaxonomicFilterGroupType.CustomEvents,
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.EventMetadata,
                TaxonomicFilterGroupType.RevenueAnalyticsProperties,
                TaxonomicFilterGroupType.NumericalEventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.CohortsWithAllUsers,
                TaxonomicFilterGroupType.Metadata,
                TaxonomicFilterGroupType.SessionProperties,
                TaxonomicFilterGroupType.ErrorTrackingProperties,
            ].includes(listGroupType) ||
                listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix))
    )
}

const canSelectItem = (listGroupType?: TaxonomicFilterGroupType): boolean => {
    return !!listGroupType && ![TaxonomicFilterGroupType.DataWarehouse].includes(listGroupType)
}

export function InfiniteList({ popupAnchorElement }: InfiniteListProps): JSX.Element {
    const {
        mouseInteractionsEnabled,
        activeTab,
        searchQuery,
        eventNames,
        allowNonCapturedEvents,
        groupType,
        value,
        taxonomicGroups,
        selectedProperties,
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
        items,
        hasRemoteDataSource,
    } = useValues(infiniteListLogic)
    const { onRowsRendered, setIndex, expand, updateRemoteItem } = useActions(infiniteListLogic)
    const [highlightedItemElement, setHighlightedItemElement] = useState<HTMLDivElement | null>(null)
    const isActiveTab = listGroupType === activeTab

    const trimmedSearchQuery = searchQuery.trim()

    // Show "Add non-captured event" option for CustomEvents group when searching
    const showNonCapturedEventOption =
        allowNonCapturedEvents &&
        (listGroupType === TaxonomicFilterGroupType.CustomEvents ||
            listGroupType === TaxonomicFilterGroupType.Events) &&
        trimmedSearchQuery &&
        trimmedSearchQuery.length > 0 &&
        !isLoading &&
        // Only show if no results found at all
        results.length === 0

    // Only show empty state if:
    // 1. There are no results
    // 2. We're not currently loading
    // 3. We have a search query (otherwise if hasRemoteDataSource=true, we're just waiting for data)
    // 4. We're not showing the non-captured event option
    const showEmptyState =
        totalListCount === 0 && !isLoading && (!!searchQuery || !hasRemoteDataSource) && !showNonCapturedEventOption

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]
        const itemGroup = getItemGroup(item, taxonomicGroups, group)
        const itemValue = item ? itemGroup?.getValue?.(item) : null

        // Normalize value to match itemValue type before comparison
        const normalizedValue = typeof itemValue === 'number' && typeof value === 'string' ? Number(value) : value

        const isSelected = listGroupType === groupType && itemValue === normalizedValue

        const isHighlighted = rowIndex === index && isActiveTab

        const isActive = itemValue ? !!selectedProperties[listGroupType]?.includes(itemValue) : false

        // Show create custom event option when there are no results
        if (showNonCapturedEventOption && rowIndex === 0) {
            const selectNonCapturedEvent = (): void => {
                selectItem(
                    itemGroup,
                    trimmedSearchQuery,
                    { name: trimmedSearchQuery, isNonCaptured: true },
                    trimmedSearchQuery
                )
            }

            return (
                <LemonRow
                    key={`item_${rowIndex}`}
                    fullWidth
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

        const commonDivProps: React.HTMLProps<HTMLDivElement> = {
            key: `item_${rowIndex}`,
            className: clsx(
                'taxonomic-list-row',
                rowIndex === index && mouseInteractionsEnabled && 'hover',
                isActive && 'active',
                isSelected && 'selected'
            ),
            onMouseOver: () => (mouseInteractionsEnabled ? setIndex(rowIndex) : setIndex(NO_ITEM_SELECTED)),
            // if the popover is not enabled then don't leave the row selected when the mouse leaves it
            onMouseLeave: () => (mouseInteractionsEnabled && !showPopover ? setIndex(NO_ITEM_SELECTED) : null),
            style: style,
            ref: isHighlighted
                ? (element) => {
                      setHighlightedItemElement(element && popupAnchorElement ? popupAnchorElement : element)
                  }
                : null,
        }

        // If there's an item to render
        if (item && itemGroup) {
            return (
                <div
                    {...commonDivProps}
                    data-attr={`prop-filter-${listGroupType}-${rowIndex}`}
                    onClick={() => {
                        return (
                            canSelectItem(listGroupType) &&
                            selectItem(itemGroup, itemValue ?? null, item, items.originalQuery)
                        )
                    }}
                >
                    {renderItemContents({
                        item,
                        listGroupType,
                        itemGroup,
                        eventNames,
                        isActive,
                    })}
                </div>
            )
        }

        // Check if this row should be the "show more" expand row:
        // - !item: No actual item data exists at this index
        // - rowIndex === totalListCount - 1: This is the last row in the visible list
        // - isExpandable: There are more items available to load/show
        // - !isLoading: We're not currently in the middle of loading data
        const isExpandRow = !item && rowIndex === totalListCount - 1 && isExpandable && !isLoading
        if (isExpandRow) {
            return (
                <div
                    {...commonDivProps}
                    className={clsx(commonDivProps.className, 'expand-row')}
                    data-attr={`expand-list-${listGroupType}`}
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

        // Otherwise show a skeleton loader
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

    const selectedItemGroup = getItemGroup(selectedItem, taxonomicGroups, group)

    return (
        <div className={clsx('taxonomic-infinite-list', showEmptyState && 'empty-infinite-list', 'h-full')}>
            {showEmptyState ? (
                <div className="no-infinite-results flex flex-col deprecated-space-y-1 items-center">
                    <IconArchive className="text-5xl text-tertiary" />
                    <span>
                        {searchQuery ? (
                            <>
                                No results for "<strong>{searchQuery}</strong>"
                            </>
                        ) : (
                            'No results'
                        )}
                    </span>
                </div>
            ) : isLoading && (!results || results.length === 0) ? (
                <div className="flex items-center justify-center h-full">
                    <Spinner className="text-3xl" />
                </div>
            ) : (
                <AutoSizer>
                    {({ height, width }) => (
                        <List
                            width={width}
                            height={height}
                            rowCount={
                                showNonCapturedEventOption
                                    ? 1
                                    : Math.max(results.length || (isLoading ? 7 : 0), totalListCount || 0)
                            }
                            overscanRowCount={100}
                            rowHeight={36} // LemonRow heights
                            rowRenderer={renderItem}
                            onRowsRendered={onRowsRendered}
                            scrollToIndex={index}
                        />
                    )}
                </AutoSizer>
            )}
            {isActiveTab &&
            selectedItemHasPopover(selectedItem, listGroupType, selectedItemGroup) &&
            showPopover &&
            selectedItem ? (
                <BindLogic
                    logic={definitionPopoverLogic}
                    props={{
                        type: selectedItemGroup.type,
                        updateRemoteItem,
                    }}
                >
                    <ControlledDefinitionPopover
                        visible={selectedItemInView}
                        item={selectedItem}
                        group={selectedItemGroup}
                        highlightedItemElement={highlightedItemElement}
                    />
                </BindLogic>
            ) : null}
        </div>
    )
}

export function getItemGroup(
    item: TaxonomicDefinitionTypes | undefined,
    groups: TaxonomicFilterGroup[],
    defaultGroup: TaxonomicFilterGroup
): TaxonomicFilterGroup {
    let group = defaultGroup

    if (item && 'group' in item) {
        const itemGroup = groups.find((g) => item.group === g.type)
        if (itemGroup) {
            group = itemGroup
        }
    }

    return group
}
