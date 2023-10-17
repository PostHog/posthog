import './InfiniteList.scss'
import '../../lemon-ui/Popover/Popover.scss'
import { Empty, Tag } from 'antd'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { BindLogic, useActions, useValues } from 'kea'
import { infiniteListLogic, NO_ITEM_SELECTED } from './infiniteListLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { EventDefinition, PropertyDefinition } from '~/types'
import { dayjs } from 'lib/dayjs'
import { STALE_EVENT_SECONDS } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'
import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { ControlledDefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { pluralize } from 'lib/utils'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useState } from 'react'

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
            <Tag className="lemonade-tag">Stale</Tag>
        </Tooltip>
    )
}

const unusedIndicator = (eventNames: string[]): JSX.Element => {
    return (
        <Tooltip
            title={
                <>
                    This property has not been seen on{' '}
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
                    , but has been seen on other events.
                </>
            }
        >
            <Tag className="lemonade-tag">Not seen</Tag>
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
        listGroupType === TaxonomicFilterGroupType.Events &&
        'id' in item &&
        (!parsedLastSeen || dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS)

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
        listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix) ? (
        <>
            <div className={clsx('taxonomic-list-row-contents', isStale && 'text-muted')}>
                {icon}
                <PropertyKeyInfo value={item.name ?? ''} disablePopover disableIcon className="w-full" />
            </div>
            {isStale && staleIndicator(parsedLastSeen)}
            {isUnusedEventProperty && unusedIndicator(eventNames)}
        </>
    ) : (
        <div className="taxonomic-list-row-contents">
            {listGroupType === TaxonomicFilterGroupType.Elements ? (
                <PropertyKeyInfo type="element" value={item.name ?? ''} disablePopover className="w-full" />
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
        // NB: also update "renderItemPopover" above
        !!item &&
        !!group?.getValue?.(item) &&
        !!listGroupType &&
        ([
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.Elements,
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.CustomEvents,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.EventFeatureFlags,
            TaxonomicFilterGroupType.NumericalEventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.Cohorts,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
        ].includes(listGroupType) ||
            listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix))
    )
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
    } = useValues(infiniteListLogic)
    const { onRowsRendered, setIndex, expand, updateRemoteItem } = useActions(infiniteListLogic)

    const [highlightedItemElement, setHighlightedItemElement] = useState<HTMLDivElement | null>(null)

    const isActiveTab = listGroupType === activeTab
    const showEmptyState = totalListCount === 0 && !isLoading

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

        return item && group ? (
            <div
                {...commonDivProps}
                data-attr={`prop-filter-${listGroupType}-${rowIndex}`}
                onClick={() => selectItem(group, itemValue ?? null, item)}
            >
                {renderItemContents({
                    item,
                    listGroupType,
                    group,
                    eventNames,
                })}
            </div>
        ) : !item && rowIndex === totalListCount - 1 && isExpandable && !isLoading ? (
            <div
                {...commonDivProps}
                className={`${commonDivProps.className} expand-row`}
                data-attr={`expand-list-${listGroupType}`}
                onClick={expand}
            >
                {group.expandLabel?.({ count: totalResultCount, expandedCount }) ??
                    `Click here to see ${expandedCount - totalResultCount} more ${pluralize(
                        expandedCount - totalResultCount,
                        'row',
                        'rows',
                        false
                    )}`}
            </div>
        ) : (
            <div
                {...commonDivProps}
                className={`${commonDivProps.className} skeleton-row`}
                data-attr={`prop-skeleton-${listGroupType}-${rowIndex}`}
            >
                <LemonSkeleton />
            </div>
        )
    }

    return (
        <div className={clsx('taxonomic-infinite-list', showEmptyState && 'empty-infinite-list')}>
            {showEmptyState ? (
                <div className="no-infinite-results">
                    <Empty
                        description={
                            <>
                                {searchQuery ? (
                                    <>
                                        No results for "<strong>{searchQuery}</strong>"
                                    </>
                                ) : (
                                    'No results'
                                )}
                            </>
                        }
                    />
                </div>
            ) : (
                <AutoSizer>
                    {({ height, width }) => (
                        <List
                            width={width}
                            height={height}
                            rowCount={isLoading && totalListCount === 0 ? 7 : totalListCount}
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
