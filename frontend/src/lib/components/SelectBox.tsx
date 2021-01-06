import React, { useRef, useEffect, useState, Fragment } from 'react'
import { useActions, useValues } from 'kea'
import { Col, Row, Input, Divider } from 'antd'
import { List } from 'antd'
import { DownOutlined, RightOutlined } from '@ant-design/icons'
import { ActionType } from '~/types'
import { searchItems, selectBoxLogic } from 'lib/logic/selectBoxLogic'
import './SelectBox.scss'
import { selectBoxLogicType } from 'types/lib/logic/selectBoxLogicType'

export interface SelectBoxItem {
    dataSource: SelectedItem[]
    renderInfo({ item }: { item: SelectedItem }): JSX.Element
    name: JSX.Element | string
}

export interface SelectedItem {
    name: string
    key: string
    action?: ActionType
    event?: string
    volume?: number
    usage_count?: number
    category?: string
}

export function SelectBox({
    items,
    selectedItemKey,
    onSelect,
    onDismiss,
}: {
    items: SelectBoxItem[]
    selectedItemKey?: string
    onSelect: CallableFunction
    onDismiss: (event: MouseEvent) => void
}): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement>(null)
    const dropdownLogic = selectBoxLogic({ updateFilter: onSelect, items })
    const { selectedItem, RenderInfo } = useValues(dropdownLogic)
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
            setSelectedItem(allSources.filter((item) => item.key === selectedItemKey)[0] || false)
            const offset = document.querySelector('.search-list [datakey="' + selectedItemKey + '"]')?.offsetTop
            document.querySelector('.search-list').scrollTop = offset
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
                        {items.map((item, index) => (
                            <Fragment key={index}>
                                <SelectUnit
                                    name={item.name}
                                    dropdownLogic={dropdownLogic}
                                    dataSource={item.dataSource}
                                />
                                <Divider />
                            </Fragment>
                        ))}
                    </div>
                </Col>
                <Col sm={10} className="info-box">
                    {RenderInfo && <RenderInfo item={selectedItem} />}
                </Col>
            </Row>
        </div>
    )
}

export function SelectUnit({
    name,
    dataSource,
    dropdownLogic,
}: {
    name: string | JSX.Element
    dataSource: SelectedItem[]
    dropdownLogic: selectBoxLogicType
}): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { setSelectedItem, clickSelectedItem } = useActions(dropdownLogic)
    const { selectedItem, search, blockMouseOver } = useValues(dropdownLogic)
    const data = !search ? dataSource : searchItems(dataSource, search)
    return (
        <>
            <span onClick={() => setIsCollapsed(!isCollapsed)}>
                <h4 style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 12px', marginBottom: 0 }}>
                    {isCollapsed || data.length === 0 ? <RightOutlined /> : <DownOutlined />} {name}
                    <span
                        style={{ float: 'right', fontWeight: search && data.length > 0 ? 700 : 'normal' }}
                        className="text-small"
                    >
                        {data.length} event{data.length !== 1 && 's'}
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
                            className={selectedItem.key === item.key ? 'selected' : undefined}
                            datakey={item.key}
                            onClick={() => clickSelectedItem(item)}
                            onMouseOver={() =>
                                !blockMouseOver && setSelectedItem({ ...item, key: item.key, category: name })
                            }
                        >
                            {item.name}
                        </List.Item>
                    )}
                />
            )}
        </>
    )
}
