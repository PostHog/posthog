import React from 'react'
import { Tabs, Tag } from 'antd'
import { useActions, useValues } from 'kea'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'
import { groups } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/groups'
import { infiniteListLogic } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/infiniteListLogic'
import { InfiniteList } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/InfiniteList'

export interface InfiniteSelectResultsProps {
    pageKey: string
    filterIndex: number
    focusInput: () => void
    onComplete: () => void
}

export function InfiniteSelectResults({
    pageKey,
    filterIndex,
    focusInput,
    onComplete,
}: InfiniteSelectResultsProps): JSX.Element {
    const filterLogic = taxonomicPropertyFilterLogic({ pageKey, filterIndex })
    const { activeTab } = useValues(filterLogic)
    const { setActiveTab } = useActions(filterLogic)

    const counts: Record<string, number> = {}
    for (const group of groups) {
        // :TRICKY: `groups` never changes, so this `useValues` hook is ran deterministically, even if in a for loop
        const logic = infiniteListLogic({ pageKey, filterIndex, type: group.type })
        counts[group.type] = useValues(logic).totalCount
    }

    return (
        <Tabs
            activeKey={activeTab || groups[0].type}
            onChange={(value) => {
                setActiveTab(value)
                focusInput()
            }}
            tabPosition="top"
            animated={false}
        >
            {groups.map(({ name, type }) => {
                const count = counts[type]
                const tabTitle = (
                    <>
                        {name} {count != null && <Tag>{count}</Tag>}
                    </>
                )
                return (
                    <Tabs.TabPane tab={tabTitle} key={type}>
                        <InfiniteList pageKey={pageKey} filterIndex={filterIndex} type={type} onComplete={onComplete} />
                    </Tabs.TabPane>
                )
            })}
        </Tabs>
    )
}
