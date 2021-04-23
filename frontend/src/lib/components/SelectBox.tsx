import React, { useRef, useEffect, useState, Fragment } from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { Col, Row, Input, Divider } from 'antd'
import { List } from 'antd'
import { DownOutlined, RightOutlined } from '@ant-design/icons'
import { ActionType, CohortType } from '~/types'
import { searchItems, selectBoxLogic } from 'lib/logic/selectBoxLogic'
import './SelectBox.scss'
import { selectBoxLogicType } from 'lib/logic/selectBoxLogicType'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export interface SelectBoxItem {
    dataSource: SelectedItem[]
    renderInfo({ item }: { item: SelectedItem }): JSX.Element
    name: JSX.Element | string
    type: string
    getValue: (item: SelectedItem) => string | number
    getLabel: (item: SelectedItem) => string
}

export interface SelectedItem {
    id?: number | string // Populated for actions (string is used for UUIDs)
    name: string
    key: string
    value?: string
    action?: ActionType
    volume_30_day?: number | null // Only for properties or events
    query_usage_30_day?: number | null // Only for properties or events
    is_numerical?: boolean // Only for properties
    category?: string
    cohort?: CohortType
}

export function SelectBox({
    items,
    selectedItemKey,
    onSelect,
    onDismiss,
}: {
    items: SelectBoxItem[]
    selectedItemKey?: string
    onSelect: (type: any, id: string | number, name: string) => void
    onDismiss: (event: MouseEvent) => void
}): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement>(null)
    const dropdownLogic = selectBoxLogic({ updateFilter: onSelect, items })
    const { selectedItem, selectedGroup } = useValues(dropdownLogic)
    const { setSearch, setSelectedItem, onKeyDown } = useActions(dropdownLogic)

    const deselect = (e: MouseEvent): void => {
        if (e.target && dropdownRef?.current?.contains(e.target as Node)) {
            return
        }
        onDismiss && onDismiss(e)
    }

    useEffect(() => {
        if (selectedItemKey) {
            const allSources = items.map((item) => item.dataSource).flat()
            setSelectedItem(allSources.filter((item) => item.key === selectedItemKey)[0] || null)
            const offset = document.querySelector<HTMLElement>('.search-list [datakey="' + selectedItemKey + '"]')
                ?.offsetTop
            const searchListSelector = document.querySelector<HTMLElement>('.search-list')
            if (offset && searchListSelector) {
                searchListSelector.scrollTop = offset
            }
        }
        document.addEventListener('mousedown', deselect)
        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('mousedown', deselect)
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [])
    return (
        <div ref={dropdownRef} className="select-box" tabIndex={0}>
            <Row style={{ height: '100%' }}>
                <Col sm={14} style={{ borderRight: '1px solid rgba(0, 0, 0, 0.1)', maxHeight: '100%' }}>
                    <Input
                        placeholder="Search events"
                        autoFocus
                        onChange={(e) => {
                            setSearch(e.target.value)
                        }}
                        style={{ width: '100%', borderRadius: 0 }}
                    />
                    <div className="search-list">
                        {items.map((group, index) => (
                            <Fragment key={index}>
                                <SelectUnit group={group} dropdownLogic={dropdownLogic} dataSource={group.dataSource} />
                                <Divider />
                            </Fragment>
                        ))}
                    </div>
                </Col>
                <Col sm={10} className="info-box">
                    {selectedGroup && selectedItem ? selectedGroup.renderInfo({ item: selectedItem }) : null}
                </Col>
            </Row>
        </div>
    )
}

export function SelectUnit({
    group,
    dataSource,
    dropdownLogic,
}: {
    group: SelectBoxItem
    dataSource: SelectedItem[]
    dropdownLogic: selectBoxLogicType<SelectedItem, SelectBoxItem> & BuiltLogic
}): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { setSelectedItem, clickSelectedItem } = useActions(dropdownLogic)
    const { selectedItem, search, blockMouseOver } = useValues(dropdownLogic)
    const data = !search ? dataSource : searchItems(dataSource, search)
    return (
        <>
            <span onClick={() => setIsCollapsed(!isCollapsed)}>
                <h4 style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 12px', marginBottom: 0 }}>
                    {isCollapsed || data.length === 0 ? <RightOutlined /> : <DownOutlined />} {group.name}
                    <span
                        style={{ float: 'right', fontWeight: search && data.length > 0 ? 700 : 'normal' }}
                        className="text-small"
                    >
                        {data.length} {data.length === 1 ? 'entry' : 'entries'}
                    </span>
                </h4>
            </span>
            {!isCollapsed && data.length > 0 && (
                <List
                    size="small"
                    bordered={false}
                    dataSource={data || []}
                    renderItem={(item: SelectedItem) => (
                        <List.Item
                            className={selectedItem?.key === item.key ? 'selected' : undefined}
                            key={item.key}
                            onClick={() => clickSelectedItem(item, group)}
                            onMouseOver={() =>
                                !blockMouseOver && setSelectedItem({ ...item, key: item.key, category: group.type })
                            }
                        >
                            <PropertyKeyInfo value={item.name} />
                        </List.Item>
                    )}
                />
            )}
        </>
    )
}
