import React from 'react'
import { List as AntDesignList, Skeleton } from 'antd'
import { List, ListRowProps, ListRowRenderer, AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { infiniteListLogic } from './infiniteListLogic'
import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/taxonomicPropertyFilterLogic'

interface InfiniteListProps {
    pageKey: string
    filterIndex: number
    type: string
}

export function InfiniteList({ pageKey, filterIndex, type }: InfiniteListProps): JSX.Element {
    const filterLogic = taxonomicPropertyFilterLogic({ pageKey, filterIndex })
    const { filter } = useValues(filterLogic)
    const { selectItem } = useActions(filterLogic)

    const listLogic = infiniteListLogic({ pageKey, filterIndex, type })
    const { results, totalCount } = useValues(listLogic)
    const { onRowsRendered } = useActions(listLogic)

    const renderItem: ListRowRenderer = ({ index, style }: ListRowProps): JSX.Element | null => {
        const item = results[index]

        const isSelected =
            item &&
            filter &&
            filter.type === type &&
            // TODO: this special case for cohorts is implemented in a few different places,
            //       and should be consolidated
            (filter.type === 'cohort' ? filter?.value === item.id : filter?.key === item.name)

        return item ? (
            <AntDesignList.Item
                className={isSelected ? 'selected' : undefined}
                key={item.id}
                onClick={() => selectItem(type, item.id, item.name)}
                style={style}
                data-attr={`prop-filter-${type}-${index}`}
            >
                <PropertyKeyInfo value={item.name} disablePopover />
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
                {({ height, width }) => (
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
