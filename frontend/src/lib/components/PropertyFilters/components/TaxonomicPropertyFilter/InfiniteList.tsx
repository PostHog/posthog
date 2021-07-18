import React, { useEffect, useRef, useState } from 'react'
import { Empty, Skeleton } from 'antd'
import { AutoSizer, List, ListRowProps, ListRowRenderer } from 'react-virtualized'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { infiniteListLogic } from './infiniteListLogic'
import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/taxonomicPropertyFilterLogic'
import { filterMatchesItem } from 'lib/components/PropertyFilters/utils'

enum ListTooltip {
    None = 0,
    Left = 1,
    Right = 2,
}

interface InfiniteListProps {
    pageKey: string
    filterIndex: number
    type: string
    onComplete: () => void
}

export function tooltipDesiredState(element?: Element | null): ListTooltip {
    let desiredState: ListTooltip = ListTooltip.None
    const rect = element?.getBoundingClientRect()
    if (rect) {
        if (window.innerWidth - rect.right > 300) {
            desiredState = ListTooltip.Right
        } else if (rect.left > 300) {
            desiredState = ListTooltip.Left
        }
    }
    return desiredState
}

export function InfiniteList({ pageKey, filterIndex, type, onComplete }: InfiniteListProps): JSX.Element {
    const filterLogic = taxonomicPropertyFilterLogic({ pageKey, filterIndex })
    const { filter, mouseInteractionsEnabled, activeTab, searchQuery } = useValues(filterLogic)
    const { selectItem } = useActions(filterLogic)

    const listLogic = infiniteListLogic({ pageKey, filterIndex, type })
    const { isLoading, results, totalCount, index } = useValues(listLogic)
    const { onRowsRendered, setIndex } = useActions(listLogic)

    // after rendering measure if there's space for a tooltip
    const [listTooltip, setListTooltip] = useState<ListTooltip>(ListTooltip.None)
    const listRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        function adjustListTooltip(): void {
            const desiredState = tooltipDesiredState(listRef?.current)
            if (listTooltip !== desiredState) {
                setListTooltip(desiredState)
            }
        }
        if (listRef?.current) {
            const resizeObserver = new ResizeObserver(adjustListTooltip)
            resizeObserver.observe(listRef.current)
            window.addEventListener('resize', adjustListTooltip)
            window.addEventListener('scroll', adjustListTooltip)
            return () => {
                resizeObserver.disconnect()
                window.removeEventListener('scroll', adjustListTooltip)
                window.removeEventListener('resize', adjustListTooltip)
            }
        }
    }, [listRef.current, index])

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const item = results[rowIndex]

        const isSelected = filterMatchesItem(filter, item, type)

        return item ? (
            <div
                key={item.id}
                className={`taxonomic-list-row${rowIndex === index ? ' hover' : ''}${isSelected ? ' selected' : ''}`}
                onClick={() => {
                    selectItem(type, item.id, item.name)
                    if (type === 'cohort') {
                        onComplete?.()
                    }
                }}
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
                    disablePopover={listTooltip === ListTooltip.None || rowIndex !== index || type !== activeTab}
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

    const showEmptyState = totalCount === 0 && !isLoading

    return (
        <div className={`taxonomic-infinite-list${showEmptyState ? ' empty-infinite-list' : ''}`} ref={listRef}>
            {showEmptyState ? (
                <div className="no-infinite-results">
                    <Empty
                        description={
                            <>
                                No results for "<strong>{searchQuery}</strong>"
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
                            rowCount={isLoading && totalCount === 0 ? 7 : totalCount}
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
