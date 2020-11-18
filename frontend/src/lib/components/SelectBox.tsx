import React, { useRef, useEffect, useState } from 'react'
import { kea, useActions, useValues } from 'kea'
import { Col, Row, Input, Divider } from 'antd'
import { actionFilterDropdownLogicType } from 'types/scenes/insights/ActionFilter/ActionFilterDropdownType'
import { List } from 'antd'
import { DownOutlined, RightOutlined } from '@ant-design/icons'
import { EntityTypes } from '../../scenes/insights/trendsLogic'
import Fuse from 'fuse.js'
import { ActionType } from '~/types'

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

const scrollUpIntoView = (key: string): void => {
    const searchList = document.querySelector('.search-list')
    const item = document.querySelector('.action-filter-dropdown [datakey="' + key + '"]')
    const diff = item?.getBoundingClientRect().top - searchList?.getBoundingClientRect().top
    if (diff - 30 < 0) searchList.scrollTop = searchList.scrollTop + diff - 30
}
const scrollDownIntoView = (key: string): void => {
    const searchList = document.querySelector('.search-list')
    const item = document.querySelector('.action-filter-dropdown [datakey="' + key + '"]')
    const diff = item?.getBoundingClientRect().top - searchList?.getBoundingClientRect().bottom
    if (diff + 30 > 0) searchList.scrollTop = searchList.scrollTop + diff + 30
}

export const actionFilterDropdownLogic = kea({
    actions: {
        setSelectedItem: (item: SelectedItem) => ({ item }),
        setSearch: (search: string) => ({ search }),
        clickSelectedItem: (item: SelectedItem) => ({ item }),
        setBlockMouseOver: (block: boolean) => ({ block }),
        onKeyDown: (e) => ({ e }),
    },
    reducers: ({ props }) => ({
        selectedItem: [
            false,
            {
                setSelectedItem: (_, { item }: { item: SelectedItem }) => item,
            },
        ],
        blockMouseOver: [
            false,
            {
                setBlockMouseOver: (_, { block }: { block: boolean }) => block,
            },
        ],
        search: [
            false,
            {
                setSearch: (_, { search }: { search: string }) => search,
            },
        ],
        RenderInfo: [
            false,
            {
                setSelectedItem: (_, { item }: { item: SelectedItem }) => {
                    console.log(item.key)
                    return props.items.filter((i) => i.dataSource.filter((i) => i.key === item.key).length > 0)[0]
                        .renderInfo
                },
            },
        ],
    }),
    listeners: ({ props, values, actions }) => ({
        clickSelectedItem: ({ item }: { item: SelectedItem }) => {
            if (item.event) {
                props.updateFilter(EntityTypes.EVENTS, item.event, item.event)
            } else {
                props.updateFilter(EntityTypes.ACTIONS, item.action.id, item.action.name)
            }
        },
        setBlockMouseOver: ({ block }) => {
            if (block) setTimeout(() => actions.setBlockMouseOver(false), 200)
        },
        onKeyDown: ({ e }) => {
            let allSources = props.items.map((item) => item.dataSource).flat()
            allSources = new Fuse(allSources, {
                keys: ['name'],
            })
                .search(values.search)
                .map((result) => result.item)
            const currentIndex = allSources.findIndex((item: SelectedItem) => item.key === values.selectedItem.key) || 0

            if (e.key === 'ArrowDown') {
                const item = allSources[currentIndex + 1]
                if (item) {
                    actions.setSelectedItem(item)
                    scrollDownIntoView(item.key)
                    actions.setBlockMouseOver(true)
                }
            }
            if (e.key === 'ArrowUp') {
                const item = allSources[currentIndex - 1]
                if (item) {
                    actions.setSelectedItem(item)
                    scrollUpIntoView(item.key)
                    actions.setBlockMouseOver(true)
                }
            }
            // if(e.key === 'Enter') {
            //     actions.clickSelectedItem(values.selectedItem)
            // }
        },
    }),
})

export function SelectBox({
    items,
    selectedItemKey,
    onSelect,
    onDismiss,
}: {
    items: SelectBoxItem[]
    selectedItemKey: string
    onSelect: CallableFunction
    onDismiss: CallableFunction
}): JSX.Element {
    const dropdownRef = useRef()
    const dropdownLogic = actionFilterDropdownLogic({ updateFilter: onSelect, items })
    const { selectedItem, RenderInfo } = useValues(dropdownLogic)
    const { setSearch, setSelectedItem, onKeyDown } = useActions(dropdownLogic)

    const deselect = (e): void => {
        if (dropdownRef.current.contains(e.target)) {
            return
        }
        onDismiss && onDismiss(e)
    }

    useEffect(() => {
        if (selectedItemKey) {
            const allSources = items.map((item) => item.dataSource).flat()
            setSelectedItem(allSources.filter((item) => item.key === selectedItemKey)[0] || false)
            const offset = document.querySelector('.action-filter-dropdown [datakey="' + selectedItemKey + '"]')
                ?.offsetTop
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
        <div ref={dropdownRef} className="action-filter-dropdown">
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
                        {items.map((item) => (
                            <>
                                <SelectUnit
                                    name={item.name}
                                    dropdownLogic={dropdownLogic}
                                    dataSource={item.dataSource}
                                />
                                <Divider />
                            </>
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
    dropdownLogic: actionFilterDropdownLogicType
}): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { setSelectedItem, clickSelectedItem } = useActions(dropdownLogic)
    const { selectedItem, search, blockMouseOver } = useValues(dropdownLogic)
    const data = !search
        ? dataSource
        : new Fuse(dataSource, {
              keys: ['name'],
          })
              .search(search)
              .map((result) => result.item)
    return (
        <>
            <span onClick={() => setIsCollapsed(!isCollapsed)}>
                <h4 style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 12px', marginBottom: 0 }}>
                    {isCollapsed || data.length === 0 ? <RightOutlined /> : <DownOutlined />} {name}
                    <span style={{ float: 'right' }} className="text-small">
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
                            className={selectedItem.key === item.key && 'selected'}
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
