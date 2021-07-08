import React from 'react'
import { List } from 'antd'
import VirtualizedList from 'react-virtualized/dist/commonjs/List'
import { ListRowProps, ListRowRenderer, AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectResult } from './InfiniteSelectResults'

interface StaticVirtualizedListProps {
    type: string
    dataSource: SelectResult[]
    onSelect: (type: string, id: string | number, name: string) => void
    selectedItemKey: string | number | null
}

export function StaticVirtualizedList({
    type,
    dataSource,
    onSelect,
    selectedItemKey,
}: StaticVirtualizedListProps): JSX.Element {
    const renderItem: ListRowRenderer = ({ index, style }: ListRowProps) => {
        const item = dataSource[index]
        return item ? (
            <List.Item
                className={selectedItemKey === item.key ? 'selected' : undefined}
                key={item.id || item.key}
                onClick={() => onSelect(type, item.key, item.name)}
                style={style}
                data-attr={`prop-filter-${item.groupName || type}-${index}`}
            >
                <PropertyKeyInfo value={item.name} />
            </List.Item>
        ) : null
    }

    return (
        <div style={{ height: '200px' }}>
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => (
                    <VirtualizedList
                        height={height}
                        overscanRowCount={0}
                        rowCount={dataSource.length}
                        rowHeight={35}
                        rowRenderer={renderItem}
                        width={width}
                        tabIndex={-1}
                    />
                )}
            </AutoSizer>
        </div>
    )
}
