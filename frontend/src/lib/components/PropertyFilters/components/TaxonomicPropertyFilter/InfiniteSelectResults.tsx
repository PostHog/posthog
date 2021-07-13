import React from 'react'
import { Tabs, Tag } from 'antd'
import { SelectedItem } from 'lib/components/SelectBox'
import { InfiniteList } from './InfiniteList'
import { useActions, useValues } from 'kea'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'
import { groups } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/groups'

export interface SelectResult extends Omit<SelectedItem, 'key'> {
    key: string | number
    tags?: string[] // TODO better type
}

export interface InfiniteSelectResultsProps {
    pageKey: string
    filterIndex: number
    onSelect: (type: string, id: string | number, name: string) => void
}

export function InfiniteSelectResults({ pageKey, filterIndex, onSelect }: InfiniteSelectResultsProps): JSX.Element {
    const filterLogic = taxonomicPropertyFilterLogic({ pageKey, filterIndex })
    const { activeTabKey, selectedItemKey, counts } = useValues(filterLogic)
    const { setActiveTabKey } = useActions(filterLogic)

    return (
        <Tabs activeKey={activeTabKey || groups[0].key} onChange={setActiveTabKey} tabPosition="top" animated={false}>
            {groups.map(({ name, key, type }) => {
                const count = counts[key]
                const tabTitle = (
                    <>
                        {name} {count != null && <Tag>{count}</Tag>}
                    </>
                )
                return (
                    <Tabs.TabPane tab={tabTitle} key={key}>
                        <InfiniteList
                            pageKey={pageKey}
                            filterIndex={filterIndex}
                            tabKey={key}
                            type={type}
                            onSelect={onSelect}
                            selectedItemKey={selectedItemKey}
                        />
                    </Tabs.TabPane>
                )
            })}
        </Tabs>
    )
}
