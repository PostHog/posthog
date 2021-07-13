import React from 'react'
import { List as AntDesignList, Skeleton } from 'antd'
import { List, ListRowProps, ListRowRenderer, AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { infiniteListLogic } from './infiniteListLogic'

interface InfiniteListProps {
    pageKey: string
    filterIndex: number
    tabKey: string
    type: string
    onSelect: (type: string, id: string | number, name: string) => void
    selectedItemKey: string | number | null
}

export function InfiniteList({
    pageKey,
    filterIndex,
    tabKey,
    type,
    onSelect,
    selectedItemKey,
}: InfiniteListProps): JSX.Element {
    const logic = infiniteListLogic({ pageKey, filterIndex, tabKey, type })
    const { results, totalCount } = useValues(logic)
    const { onRowsRendered } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index, style }: ListRowProps): JSX.Element | null => {
        const item = results[index]
        return item ? (
            <AntDesignList.Item
                className={selectedItemKey === item.id ? 'selected' : undefined}
                key={item.id}
                onClick={() => onSelect(type, item.id, item.name)}
                style={style}
                data-attr={`prop-filter-${type}-${index}`}
            >
                <PropertyKeyInfo value={item.name} />
            </AntDesignList.Item>
        ) : (
            <AntDesignList.Item key={`__skeleton_${index}`} style={style} data-attr={`prop-filter-${type}-${index}`}>
                <Skeleton active title={false} paragraph={{ rows: 1 }} />
            </AntDesignList.Item>
        )
    }

    return (
        <div style={{ minHeight: '200px' }}>
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => (
                    <List
                        width={width}
                        height={height}
                        rowCount={totalCount}
                        overscanRowCount={100}
                        rowHeight={32}
                        rowRenderer={renderItem}
                        onRowsRendered={onRowsRendered}
                    />
                )}
            </AutoSizer>
        </div>
    )
}
