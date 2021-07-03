import React from 'react'
import { Col, Row, Tabs } from 'antd'
import { SelectedItem } from 'lib/components/SelectBox'
import { useActions, useValues } from 'kea'
import { infiniteSelectResultsLogic } from 'lib/components/PropertyFilters/infiniteSelectResultsLogic'
import { InfiniteList } from './InfiniteList'
import { StaticVirtualizedList } from './StaticVirtualizedList'

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
