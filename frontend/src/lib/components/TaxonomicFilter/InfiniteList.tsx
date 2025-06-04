import './InfiniteList.scss'
import '../../lemon-ui/Popover/Popover.scss'

import { IconArchive } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
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
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils'
import { isDefinitionStale } from 'lib/utils/definitions'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'

import { EventDefinition, PropertyDefinition } from '~/types'

import { infiniteListLogic, NO_ITEM_SELECTED } from './infiniteListLogic'

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
    group,
    eventNames,
}: {
    item: TaxonomicDefinitionTypes
    listGroupType: TaxonomicFilterGroupType
    group: TaxonomicFilterGroup
    eventNames: string[]
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

    const icon = <div className="taxonomic-list-row-contents-icon">{group.getIcon?.(item)}</div>

    return listGroupType === TaxonomicFilterGroupType.EventProperties ||
        listGroupType === TaxonomicFilterGroupType.EventFeatureFlags ||
        listGroupType === TaxonomicFilterGroupType.NumericalEventProperties ||
        listGroupType === TaxonomicFilterGroupType.PersonProperties ||
        listGroupType === TaxonomicFilterGroupType.Events ||
        listGroupType === TaxonomicFilterGroupType.CustomEvents ||
        listGroupType === TaxonomicFilterGroupType.Metadata ||
        listGroupType === TaxonomicFilterGroupType.SessionProperties ||
        listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix) ? (
        <>
            <div className={clsx('taxonomic-list-row-contents', isStale && 'text-muted')}>
                {icon}
                <PropertyKeyInfo
                    value={item.name ?? ''}
                    disablePopover
                    disableIcon
                    className="w-full"
                    type={listGroupType}
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
                    {group.getIcon ? icon : null}
                    <span className="truncate" title={group.getName?.(item) || item.name || ''}>
                        {group.getName?.(item) || item.name || ''}
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
    return (
        // NB: also update "renderItemContents" above
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
        ].includes(listGroupType) ||
            listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix))
    )
}

const canSelectItem = (listGroupType?: TaxonomicFilterGroupType): boolean => {
    return !!listGroupType && ![TaxonomicFilterGroupType.DataWarehouse].includes(listGroupType)
}

export function InfiniteList({ popupAnchorElement }: InfiniteListProps): JSX.Element {
    const { mouseInteractionsEnabled, activeTab, searchQuery, value, groupType, eventNames } =
        useValues(taxonomicFilterLogic)
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

    // Only show empty state if:
    // 1. There are no results
    // 2. We're not currently loading
    // 3. We have a search query (otherwise if hasRemoteDataSource=true, we're just waiting for data)
    const showEmptyState = totalListCount === 0 && !isLoading && (!!searchQuery || !hasRemoteDataSource)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]
        const itemValue = item ? group?.getValue?.(item) : null
        const isSelected = listGroupType === groupType && itemValue === value
        const isHighlighted = rowIndex === index && isActiveTab

        const commonDivProps: React.HTMLProps<HTMLDivElement> = {
            key: `item_${rowIndex}`,
            className: clsx(
                'taxonomic-list-row',
                rowIndex === index && mouseInteractionsEnabled && 'hover',
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
        if (item && group) {
            return (
                <div
                    {...commonDivProps}
                    data-attr={`prop-filter-${listGroupType}-${rowIndex}`}
                    onClick={() => {
                        return (
                            canSelectItem(listGroupType) &&
                            selectItem(group, itemValue ?? null, item, items.originalQuery)
                        )
                    }}
                >
                    {renderItemContents({
                        item,
                        listGroupType,
                        group,
                        eventNames,
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
            ) : isLoading &&
              (!results ||
                  results.length === 0 ||
                  (results.length === 1 && (!results[0].id || results[0].id === ''))) ? (
                <div className="flex items-center justify-center h-full">
                    <Spinner className="text-3xl" />
                </div>
            ) : (
                <AutoSizer>
                    {({ height, width }) => (
                        <List
                            width={width}
                            height={height}
                            rowCount={Math.max(results.length || (isLoading ? 7 : 0), totalListCount || 0)}
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
            selectedItemHasPopover(selectedItem, listGroupType, group) &&
            showPopover &&
            selectedItem ? (
                <BindLogic
                    logic={definitionPopoverLogic}
                    props={{
                        type: listGroupType,
                        updateRemoteItem,
                    }}
                >
                    <ControlledDefinitionPopover
                        visible={selectedItemInView}
                        item={selectedItem}
                        group={group}
                        highlightedItemElement={highlightedItemElement}
                    />
                </BindLogic>
            ) : null}
        </div>
    )
}
