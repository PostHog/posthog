import React, { useEffect } from 'react'
import { Col, Row, Tabs, List } from 'antd'
import AutoSizer from 'react-virtualized/dist/commonjs/AutoSizer'
import VirtualizedList from 'react-virtualized/dist/commonjs/List'
import { InfiniteLoader, ListRowProps, ListRowRenderer } from 'react-virtualized'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectedItem } from 'lib/components/SelectBox'

import { useThrottledCallback } from 'use-debounce/lib'
import { Loading } from 'lib/utils'
import { infiniteSelectResultsLogic } from '../infiniteSelectResultsLogic'
import { useActions, useValues } from 'kea'
import { infiniteListLogic } from '../infiniteListLogic'

export interface SelectResult extends Omit<SelectedItem, 'key'> {
    key: string | number
    tags?: string[] // TODO better type
}

export interface SelectResultGroup {
    key: string
    name: string
    type: string
    endpoint?: string // Endpoint supporting search and pagination
    dataSource?: SelectResult[] // Static options (instead of fetching from endpoint)
}

export interface InfiniteSelectResultsProps {
    pageKey: string
    groups: SelectResultGroup[]
    searchQuery?: string // Search query for endpoint if defined, else simple filter on dataSource
    onSelect: (type: string, id: string | number, name: string) => void
    selectedItemKey?: string | number | null
    defaultActiveTabKey?: string
}

export function InfiniteSelectResults({
    pageKey,
    groups,
    searchQuery,
    onSelect,
    selectedItemKey = null,
    defaultActiveTabKey,
}: InfiniteSelectResultsProps): JSX.Element {
    const initialActiveTabKey = defaultActiveTabKey || groups[0]?.key
    const logic = infiniteSelectResultsLogic({ pageKey, groups, initialActiveTabKey })
    const { activeTabKey } = useValues(logic)
    const { setActiveTabKey } = useActions(logic)

    const handleSelect = (type: string, key: string | number, name: string): void => {
        onSelect(type, key, name)
    }

    return (
        <Row gutter={8} style={{ width: '100%' }} wrap={false}>
            <Col flex={1}>
                <Tabs
                    defaultActiveKey={initialActiveTabKey}
                    onChange={setActiveTabKey}
                    tabPosition="top"
                    animated={false}
                >
                    {groups.map(({ key, name, type, endpoint, dataSource }) => (
                        <Tabs.TabPane tab={name} key={key} active={activeTabKey === key}>
                            {endpoint && !dataSource ? (
                                <InfiniteList
                                    pageKey={pageKey}
                                    type={type}
                                    endpoint={endpoint}
                                    searchQuery={searchQuery}
                                    onSelect={handleSelect}
                                    selectedItemKey={selectedItemKey}
                                />
                            ) : (
                                <StaticVirtualizedList
                                    type={type}
                                    dataSource={dataSource || []}
                                    searchQuery={searchQuery}
                                    onSelect={handleSelect}
                                    selectedItemKey={selectedItemKey}
                                />
                            )}
                        </Tabs.TabPane>
                    ))}
                </Tabs>
            </Col>
        </Row>
    )
}

interface InfiniteListProps {
    pageKey: string
    type: string
    endpoint: string
    searchQuery?: string
    onSelect: InfiniteSelectResultsProps['onSelect']
    selectedItemKey: string | number | null
}

function InfiniteList({ pageKey, type, endpoint, searchQuery, onSelect, selectedItemKey }: InfiniteListProps): JSX.Element {
    const logic = infiniteListLogic({ pageKey, type, endpoint })
    const { results, itemsLoading, totalCount } = useValues(logic)
    const { loadItems } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index, style }: ListRowProps): JSX.Element | null => {
        const item = results[index]
        return item ? (
            <List.Item
                className={selectedItemKey === item.id ? 'selected' : undefined}
                key={item.id}
                onClick={() => onSelect(type, item.id, item.name)}
                style={style}
                data-attr={`prop-filter-${type}-${index}`}
            >
                <PropertyKeyInfo value={item.name} />
            </List.Item>
        ) : null
    }

    useEffect(
        useThrottledCallback(() => {
            // TODO breakpoint in loadItems
            loadItems({ search: searchQuery })
        }, 100),
        [searchQuery]
    )

    return (
        <div style={{ minHeight: '200px' }}>
            {itemsLoading && <Loading />}
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => (
                    <InfiniteLoader
                        isRowLoaded={({ index }) => !!results[index]}
                        loadMoreRows={({ startIndex, stopIndex }) => {
                            // TODO async load and return Promise<results>
                            loadItems({ search: searchQuery, offset: startIndex, limit: stopIndex - startIndex })
                        }}
                        rowCount={totalCount || 0}
                    >
                        {({ onRowsRendered, registerChild }) => (
                            <VirtualizedList
                                height={height}
                                onRowsRendered={onRowsRendered}
                                ref={registerChild}
                                overscanRowCount={0}
                                rowCount={totalCount || 0}
                                rowHeight={35}
                                rowRenderer={renderItem}
                                width={width}
                                tabIndex={-1}
                            />
                        )}
                    </InfiniteLoader>
                )}
            </AutoSizer>
        </div>
    )
}

interface StaticVirtualizedListProps {
    type: string
    dataSource: SelectResult[]
    searchQuery?: string
    onSelect: (type: string, id: string | number, name: string) => void
    selectedItemKey: string | number | null
}

export function StaticVirtualizedList({
    type,
    dataSource,
    searchQuery,
    onSelect,
    selectedItemKey,
}: StaticVirtualizedListProps): JSX.Element {
    let items = dataSource
    if (searchQuery) {
        items = dataSource.filter(({ name }) => name.match(searchQuery))
    }

    const renderItem: ListRowRenderer = ({ index, style }: ListRowProps) => {
        const item = items[index]
        return item ? (
            <List.Item
                className={selectedItemKey === item.key ? 'selected' : undefined}
                key={item.id}
                onClick={() => onSelect(type, item.key, item.name)}
                style={style}
                data-attr={`prop-filter-${item.groupName || type}-${index}`}
            >
                <PropertyKeyInfo value={item.name} />
            </List.Item>
        ) : null
    }

    return (
        <div style={{ height: '200px', width: '350px' }}>
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => (
                    <VirtualizedList
                        height={height}
                        overscanRowCount={0}
                        rowCount={items.length}
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
