import React from 'react'
import { Tabs } from 'antd'
import { SelectedItem } from 'lib/components/SelectBox'
import { InfiniteList } from './InfiniteList'
import { StaticVirtualizedList } from './StaticVirtualizedList'
import { useActions, useValues } from 'kea'
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

export function InfiniteSelectResults({ filterKey, groups, onSelect }: InfiniteSelectResultsProps): JSX.Element {
    const filterLogic = taxonomicPropertyFilterLogic({ key: filterKey })
    const { activeTabKey, searchQuery, selectedItemKey } = useValues(filterLogic)
    const { setActiveTabKey } = useActions(filterLogic)
    const handleSelect = (type: string, key: string | number, name: string): void => {
        onSelect(type, key, name)
    }

    return (
        <Tabs
            defaultActiveKey={activeTabKey || groups[0].key}
            onChange={setActiveTabKey}
            tabPosition="top"
            animated={false}
        >
            {groups.map(({ key, name, type, endpoint, dataSource }) => (
                <Tabs.TabPane tab={name} key={key} active={activeTabKey === key}>
                    {endpoint && !dataSource ? (
                        <InfiniteList
                            filterKey={filterKey}
                            tabKey={key}
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
    )
}
