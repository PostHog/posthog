import React from 'react'
import { Tabs, Tag } from 'antd'
import { SelectedItem } from 'lib/components/SelectBox'
import { InfiniteList } from './InfiniteList'
import { StaticVirtualizedList } from './StaticVirtualizedList'
import { useActions, useValues } from 'kea'
import Fuse from 'fuse.js'
import { taxonomicPropertyFilterLogic } from '../../taxonomicPropertyFilterLogic'

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
    filterKey: string
    groups: SelectResultGroup[]
    onSelect: (type: string, id: string | number, name: string) => void
}

const fuseCache: Record<string, Fuse<SelectResult>> = {}

const searchItems = (sources: SelectResult[], groupType: string, search?: string): SelectResult[] => {
    if (!search) {
        return sources
    }

    if (!fuseCache[groupType]) {
        fuseCache[groupType] = new Fuse(sources, {
            keys: ['name'],
            threshold: 0.3,
        })
    }
    return fuseCache[groupType].search(search).map((result) => result.item)
}

export function InfiniteSelectResults({ filterKey, groups, onSelect }: InfiniteSelectResultsProps): JSX.Element {
    const filterLogic = taxonomicPropertyFilterLogic({ key: filterKey })
    const { activeTabKey, searchQuery, selectedItemKey, groupMetadata } = useValues(filterLogic)
    const { setActiveTabKey, setGroupMetadataEntry } = useActions(filterLogic)
    const handleSelect = (type: string, key: string | number, name: string): void => {
        onSelect(type, key, name)
    }
    const updateCount = (key: string) => (count: number): void => {
        setGroupMetadataEntry(key, { count })
    }

    return (
        <Tabs
            defaultActiveKey={activeTabKey || groups[0].key}
            onChange={setActiveTabKey}
            tabPosition="top"
            animated={false}
        >
            {groups.map(({ key, type, endpoint, dataSource }) => {
                const { name, count, active } = groupMetadata[key] || {}
                if (endpoint && !dataSource) {
                    const title = (
                        <>
                            {name} {count != null && <Tag>{count}</Tag>}
                        </>
                    )
                    return (
                        <Tabs.TabPane tab={title} key={key} active={active}>
                            <InfiniteList
                                filterKey={filterKey}
                                tabKey={key}
                                type={type}
                                endpoint={endpoint}
                                searchQuery={searchQuery}
                                onSelect={handleSelect}
                                selectedItemKey={selectedItemKey}
                                updateCount={updateCount(key)}
                            />
                        </Tabs.TabPane>
                    )
                } else {
                    const searchResults = searchItems(dataSource || [], type, searchQuery)
                    const title = (
                        <>
                            {name} <Tag>{searchResults.length}</Tag>
                        </>
                    )
                    return (
                        <Tabs.TabPane tab={title} key={key} active={active}>
                            <StaticVirtualizedList
                                type={type}
                                dataSource={searchResults}
                                onSelect={handleSelect}
                                selectedItemKey={selectedItemKey}
                            />
                        </Tabs.TabPane>
                    )
                }
            })}
        </Tabs>
    )
}
