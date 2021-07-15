import React from 'react'
import { Skeleton } from 'antd'
import { List, ListRowProps, ListRowRenderer, AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { infiniteListLogic } from './infiniteListLogic'
import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/taxonomicPropertyFilterLogic'
import { filterMatchesItem } from 'lib/components/PropertyFilters/utils'

interface InfiniteListProps {
    pageKey: string
    filterIndex: number
    type: string
}

export function InfiniteList({ pageKey, filterIndex, type }: InfiniteListProps): JSX.Element {
    const filterLogic = taxonomicPropertyFilterLogic({ pageKey, filterIndex })
    const { filter, mouseInteractionsEnabled } = useValues(filterLogic)
    const { selectItem } = useActions(filterLogic)

    const listLogic = infiniteListLogic({ pageKey, filterIndex, type })
    const { results, totalCount, index } = useValues(listLogic)
    const { onRowsRendered, setIndex } = useActions(listLogic)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]

        const isSelected = filterMatchesItem(filter, item, type)

        return item ? (
            <div
                key={item.id}
                className={`taxonomic-list-row${rowIndex === index ? ' hover' : ''}${isSelected ? ' selected' : ''}`}
                onClick={() => selectItem(type, item.id, item.name)}
                onMouseOver={() => mouseInteractionsEnabled && setIndex(rowIndex)}
                style={style}
                data-attr={`prop-filter-${type}-${rowIndex}`}
            >
                <PropertyKeyInfo value={item.name} disablePopover />
            </div>
        ) : (
            <div
                key={`__skeleton_${rowIndex}`}
                className={`taxonomic-list-row skeleton-row${rowIndex === index ? ' hover' : ''}`}
                onMouseOver={() => mouseInteractionsEnabled && setIndex(rowIndex)}
                style={style}
                data-attr={`prop-filter-${type}-${rowIndex}`}
            >
                <Skeleton active title={false} paragraph={{ rows: 1 }} />
            </div>
        )
    }

    return (
        <div className="taxonomic-infinite-list">
            <AutoSizer>
                {({ height, width }) => (
                    <List
                        width={width}
                        height={height}
                        rowCount={totalCount}
                        overscanRowCount={100}
                        rowHeight={32}
                        rowRenderer={renderItem}
                        onRowsRendered={onRowsRendered}
                        scrollToIndex={index}
                    />
                )}
            </AutoSizer>
        </div>
    )
}
