import React, { useEffect, useState } from 'react'
import { Col, Row, Tabs, List } from 'antd'
import AutoSizer from 'react-virtualized/dist/commonjs/AutoSizer'
import VirtualizedList from 'react-virtualized/dist/commonjs/List'
import { InfiniteLoader, ListRowProps, ListRowRenderer } from 'react-virtualized'

import { EventDefinition } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectedItem } from 'lib/components/SelectBox'
import api from 'lib/api'


interface SelectResult extends SelectedItem {
    tags?: string[] // TODO better type
}

interface SelectResultGroup {
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
    groups: SelectResultGroup[]
    searchQuery?: string // Search query for endpoint if defined, else simple filter on dataSource
    onSelect: (type: any, id: string | number, name: string) => void
}

export function InfiniteSelectResults({
    groups,
    searchQuery,
    onSelect,
}: InfiniteSelectResultsProps): JSX.Element {
    const defaultActiveKey = groups[0]?.key || undefined
    const [activeKey, setActiveKey] = useState(defaultActiveKey)
    return (
        <Row gutter={8} className="full-width" wrap={false}>
            <Col flex={1} style={{ minWidth: '11rem' }}>
                <Tabs
                    defaultActiveKey={defaultActiveKey}
                    onChange={setActiveKey}
                    tabPosition="top"
                    animated={false}
                >
                    {groups.map(({ key, name, type, endpoint, dataSource }) => (
                        <Tabs.TabPane
                            tab={name}
                            key={key}
                            active={activeKey === key}
                        >
                            {(endpoint && !dataSource) ? (
                                <InfiniteList
                                    type={type}
                                    endpoint={endpoint}
                                    searchQuery={searchQuery}
                                    onSelect={onSelect}
                                />
                            ) : (
                                <StaticVirtualizedList
                                    type={type}
                                    dataSource={dataSource?.filter(({ groupName }) => groupName === type) || []}
                                    searchQuery={searchQuery}
                                    onSelect={onSelect}
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
    type: string
    endpoint: string
    searchQuery?: string
    onSelect: InfiniteSelectResultsProps['onSelect']
}

function buildUrl(url: string, queryParams?: Record<string, any>): string {
    let result = url
    if(queryParams) {
        const initialChar = url.indexOf('?') !== -1 ? '&' : '?'
        result += initialChar
        const searchString = Object.entries(queryParams)
            .filter(([, value]) => value !== undefined)
            .map(([key, value]) => `${key}=${value}`)
            .join('&')
        result += searchString
    }
    return result
}

function InfiniteList({
    type,
    endpoint,
    searchQuery,
    onSelect,
}: InfiniteListProps): JSX.Element {
    const [items, setItems] = useState<EventDefinition[]>([])
    const [totalCount, setTotalCount] = useState<number | null>(null)
    const [next, setNext] = useState<string | null>(null)

    const isRowLoaded = ({ index }: { index: number }): boolean => {
        return Boolean(items[index])
    }

    const loadInitialRows = async (): Promise<any> => {
        try {
            const url = buildUrl(endpoint, {
                search: searchQuery,
                limit: 100,
                offset: 0,
            })
            const response: EventDefinitionResult = await api.get(url)
            setTotalCount(response.count)
            setNext(response.next)
            setItems(response.results)
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
                setItems(previousItems => [...previousItems, ...response.results])
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
                // className={selectedItem?.key === item.key ? 'selected' : undefined}
                key={item.id}
                // onClick={() => clickSelectedItem(item, group)}
                style={style}
                // onMouseOver={() =>
                //     !blockMouseOver && setSelectedItem({ ...item, key: item.key, category: group.type })
                // }
            >
                <PropertyKeyInfo value={item.name} />
            </List.Item>
        ) : null
    }

    useEffect(() => {
        loadInitialRows()
    }, [])

    return (
        <div style={{ height: '200px', width: '350px' }}>
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => (
                    <InfiniteLoader
                        isRowLoaded={isRowLoaded}
                        loadMoreRows={loadMoreRows}
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

