import React, { useEffect, useState } from 'react'
import { Col, Row, Tabs, List } from 'antd'
import AutoSizer from 'react-virtualized/dist/commonjs/AutoSizer'
import VirtualizedList from 'react-virtualized/dist/commonjs/List'
import { InfiniteLoader, ListRowProps, ListRowRenderer } from 'react-virtualized'

import { EventDefinition } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectedItem } from 'lib/components/SelectBox'
import api from 'lib/api'

import { useThrottledCallback } from 'use-debounce/lib'
import { Loading, buildUrl } from 'lib/utils'
import { infiniteSelectResultsLogic } from '../infiniteSelectResultsLogic'
import { useActions, useValues } from 'kea'

interface SelectResult extends Omit<SelectedItem, 'key'> {
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

type EventDefinitionResult = {
    count: number
    next: null | string
    results: EventDefinition[]
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

function transformResults(results: EventDefinitionResult['results']): SelectResult[] {
    return results.map((definition) => ({
        ...definition,
        key: definition.id,
    }))
}

interface InfiniteListProps {
    type: string
    endpoint: string
    searchQuery?: string
    onSelect: InfiniteSelectResultsProps['onSelect']
    selectedItemKey: string | number | null
}

function InfiniteList({ type, endpoint, searchQuery, onSelect, selectedItemKey }: InfiniteListProps): JSX.Element {
    const [items, setItems] = useState<SelectResult[]>([])
    const [loading, setLoading] = useState(false)
    const [totalCount, setTotalCount] = useState<number | null>(null)
    const [next, setNext] = useState<string | null>(null)

    const isRowLoaded = ({ index }: { index: number }): boolean => {
        return Boolean(items[index])
    }

    const loadInitialRows = async (search?: string): Promise<any> => {
        try {
            const url = buildUrl(endpoint, {
                search,
                limit: 100,
                offset: 0,
            })
            setLoading(true)
            const response: EventDefinitionResult = await api.get(url)
            setTotalCount(response.count)
            setNext(response.next)
            setItems(transformResults(response.results))
            setLoading(false)
        } catch (err) {
            console.error(err)
        }
    }

    const loadMoreRows = async ({ startIndex }: { startIndex: number }): Promise<any> => {
        const [, , nextOffset] = next?.match(/(offset=)(\d*)/) || []
        // Only load values not yet in state
        if (startIndex >= items.length && parseInt(nextOffset) >= items.length) {
            try {
                const response: EventDefinitionResult = await api.get(next)
                setTotalCount(response.count)
                setNext(response.next)
                setItems((previousItems) => [...previousItems, ...transformResults(response.results)])
                return response.results
            } catch (err) {
                console.error(err)
            }
        }
    }

    const renderItem: ListRowRenderer = ({ index, style }: ListRowProps): JSX.Element | null => {
        const item = items[index]
        return item ? (
            <List.Item
                className={selectedItemKey === item.id ? 'selected' : undefined}
                key={item.id}
                onClick={() => onSelect(type, item.key, item.name)}
                style={style}
                data-attr={`prop-filter-${item.groupName || type}-${index}`}
            >
                <PropertyKeyInfo value={item.name} />
            </List.Item>
        ) : null
    }

    useEffect(() => {
        loadInitialRows()
    }, [])

    useEffect(
        useThrottledCallback(() => {
            loadInitialRows(searchQuery)
        }, 100),
        [searchQuery]
    )

    return (
        <div style={{ minHeight: '200px' }}>
            {loading && <Loading />}
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => (
                    <InfiniteLoader isRowLoaded={isRowLoaded} loadMoreRows={loadMoreRows} rowCount={totalCount || 0}>
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
