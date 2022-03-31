import './SearchList.scss'
import '../Popup/Popup.scss'
import React from 'react'
import { Empty, Skeleton, Tag } from 'antd'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { searchListLogic, NO_ITEM_SELECTED } from './searchListLogic'
import { universalSearchLogic } from './universalSearchLogic'
import { EventDefinition, PersonType } from '~/types'
import { dayjs } from 'lib/dayjs'
import { FEATURE_FLAGS, STALE_EVENT_SECONDS } from 'lib/constants'
import { Tooltip } from '../Tooltip'
import clsx from 'clsx'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { SearchDefinitionTypes, UniversalSearchGroup, UniversalSearchGroupType } from './types'

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

const renderItemContents = ({
    item,
    listGroupType,
    group,
    featureFlags,
}: {
    item: SearchDefinitionTypes
    listGroupType: UniversalSearchGroupType
    group: UniversalSearchGroup
    featureFlags: FeatureFlagsSet
}): JSX.Element | string => {
    const parsedLastSeen = (item as EventDefinition).last_seen_at ? dayjs((item as EventDefinition).last_seen_at) : null
    const isStale =
        (listGroupType === UniversalSearchGroupType.Events && !parsedLastSeen) ||
        dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS

    return listGroupType === UniversalSearchGroupType.Persons || listGroupType === UniversalSearchGroupType.Events ? (
        <>
            <div className={clsx('taxonomic-list-row-contents', isStale && 'text-muted')}>
                <PropertyKeyInfo
                    value={(item as EventDefinition | PersonType).name ?? ''}
                    disablePopover
                    disableIcon={!!featureFlags[FEATURE_FLAGS.DATA_MANAGEMENT]}
                    style={{ maxWidth: '100%' }}
                />
            </div>
            {isStale && staleIndicator(parsedLastSeen)}
        </>
    ) : (
        <>{(item.name || group.getName(item)) ?? ''}</>
    )
}

export function SearchList(): JSX.Element {
    const { mouseInteractionsEnabled, searchQuery, value, groupType } = useValues(universalSearchLogic)
    const { selectItem } = useActions(universalSearchLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { isLoading, results, index, listGroupType, group, totalResultCount, showPopover } =
        useValues(searchListLogic)
    const { onRowsRendered, setIndex } = useActions(searchListLogic)

    const showEmptyState = totalResultCount === 0 && !isLoading

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]
        const itemValue = item ? group?.getValue?.(item) : null
        const isSelected = listGroupType === groupType && itemValue === value

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
                    featureFlags,
                })}
            </div>
        ) : (
            <div
                {...commonDivProps}
                className={`${commonDivProps.className} skeleton-row`}
                data-attr={`prop-skeleton-${listGroupType}-${rowIndex}`}
            >
                <Skeleton active title={false} paragraph={{ rows: 1 }} />
            </div>
        )
    }

    return (
        <div
            className={clsx('taxonomic-infinite-list', showEmptyState && 'empty-infinite-list')}
            style={{ flexGrow: 1 }}
        >
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
                            rowCount={isLoading && totalResultCount === 0 ? 7 : totalResultCount}
                            overscanRowCount={100}
                            rowHeight={32}
                            rowRenderer={renderItem}
                            onRowsRendered={onRowsRendered}
                            scrollToIndex={index}
                        />
                    )}
                </AutoSizer>
            )}
        </div>
    )
}
