import React, { useEffect, useRef } from 'react'
import { Skeleton } from 'antd'
import { AutoSizer, List, ListRowProps, ListRowRenderer } from 'react-virtualized'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { infiniteListLogic, ListTooltip } from './infiniteListLogic'
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
    const { results, totalCount, index, listTooltip } = useValues(listLogic)
    const { onRowsRendered, setIndex, setListTooltip } = useActions(listLogic)

    // after rendering measure if there's space for a tooltip
    const listRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        const rect = listRef.current?.getBoundingClientRect()
        let desiredState: ListTooltip = ListTooltip.None
        if (rect) {
            if (window.innerWidth - rect.right > 300) {
                desiredState = ListTooltip.Right
            } else if (rect.left > 300) {
                desiredState = ListTooltip.Left
            }
        }
        if (listTooltip !== desiredState) {
            setListTooltip(desiredState)
        }
    }, [index])

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]

        const isSelected = filterMatchesItem(filter, item, type)

        return item ? (
            <div
                key={item.id}
                className={`taxonomic-list-row${rowIndex === index ? ' hover' : ''}${isSelected ? ' selected' : ''}`}
                onClick={() => selectItem(type, item.id, item.name)}
                onMouseOver={() => {
                    if (mouseInteractionsEnabled) {
                        setIndex(rowIndex)
                    }
                }}
                style={style}
                data-attr={`prop-filter-${type}-${rowIndex}`}
            >
                <PropertyKeyInfo
                    value={item.name}
                    disablePopover={listTooltip === ListTooltip.None || rowIndex !== index}
                    tooltipPlacement={listTooltip === ListTooltip.Left ? 'left' : 'right'}
                />
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
        <div className="taxonomic-infinite-list" ref={listRef}>
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
