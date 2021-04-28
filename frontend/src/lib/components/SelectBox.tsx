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

import WindowScroller from 'react-virtualized/dist/commonjs/WindowScroller';
import AutoSizer from 'react-virtualized/dist/commonjs/AutoSizer';
import VList, { RenderedRows } from 'react-virtualized/dist/commonjs/List';
import InfiniteLoader from 'react-virtualized/dist/commonjs/InfiniteLoader';
import ScrollSync from 'react-virtualized/dist/commonjs/ScrollSync'
import { IndexRange, InfiniteLoaderProps, ListRowProps, ListRowRenderer, OnScrollParams, ScrollParams } from 'react-virtualized'

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
                    <div style={{width: '100%', height: '100%'}}>
                        <SelectUnit items={items} dropdownLogic={dropdownLogic} />
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
    dropdownLogic,
    items
}: {
    dropdownLogic: selectBoxLogicType<SelectedItem, SelectBoxItem> & BuiltLogic
    items: SelectBoxItem[]
}): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { setSelectedItem, clickSelectedItem } = useActions(dropdownLogic)
    const { selectedItem, search, blockMouseOver } = useValues(dropdownLogic)
    const [hiddenData, setHiddenData] = useState<Record<string, { key: string; name: string; }[]>>({})
    const [data, setData] = useState<Record<string, { key: string; name: string; }[]>>({})
    const [flattenedData, setFlattenedData] = useState<{ key: string; name: string; }[]>([])
    const [groupTypes, setGroupTypes] = useState<string[]>([])
    useEffect(() => {
        let formattedData: Record<string, SelectedItem[]> = {}
        const groupTypes: string[] = []
        items.forEach(group => {
            formattedData[group.type] = group.dataSource
            groupTypes.push(group.type)
        })
        setGroupTypes(groupTypes)
        setData(formattedData)
    }, [])
    console.log(items)
    useEffect(() => {
        const flattenedData: { key: string; name: string; }[] = []
        Object.keys(data).forEach(key => {
            flattenedData.push({
                key: key,
                name: key
            })
            flattenedData.push(...data[key])
        })
        setFlattenedData(flattenedData)
    }, [data])

    const hideKey = (key: string) => {
        const { [`${key}`]: hideItem, ...restOfData} = data
        const copy = {
            ...data
        }
        copy[key] = []
        setData(copy)
        setHiddenData({
            ...hiddenData,
            [`${key}`]: hideItem
        })
    }

    const showKey = (key: string) => {
        const { [`${key}`]: showItem, ...restOfData} = hiddenData
        setHiddenData(restOfData)
        const copy = {
            ...data
        }
        copy[key] = showItem
        setData(copy)
    }

    const renderItem: ListRowRenderer = ({index, style}: ListRowProps) => {
        const item = flattenedData[index]
        if(groupTypes.includes(item.key)) {
             return <div style={style}>
                 <span onClick={() => hiddenData?.[item.key] ? showKey(item.key) : hideKey(item.key)} key={item.key}>
                <h4 style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 12px', marginBottom: 0 }}>
                    {hiddenData?.[item.key] ? <RightOutlined /> : <DownOutlined />} {item.key}
                    <span
                        style={{ float: 'right', fontWeight: search && flattenedData.length > 0 ? 700 : 'normal' }}
                        className="text-small"
                    >
                        {data.length} {flattenedData.length === 1 ? 'entry' : 'entries'}
                    </span>
                </h4>
            </span>
             </div>
        } else {
            return (
                <List.Item
                    className={selectedItem?.key === item.key ? 'selected' : undefined}
                    key={item.key}
                    // onClick={() => clickSelectedItem(item, group)}
                    style={style}
                    onMouseOver={() => {}
                        // !blockMouseOver && setSelectedItem({ ...item, key: item.key, category: group.type })
                    }
                >
                    <PropertyKeyInfo value={item.name} />
                </List.Item>
            )
        }
    }

    const vlist = ({ 
        height, 
        width
    }: {
        height: number, 
        width: number,
    }) => (
        <VList
          height={height}
          overscanRowCount={0}
          rowCount={flattenedData.length}
          rowHeight={35}
          rowRenderer={renderItem}
          width={width}
        />
    );


    return (
        <>
            {!isCollapsed && flattenedData.length > 0 && (
                <div style={{height: '100%'}}>
                    {
                        <AutoSizer>
                            {({ height,width }: {height: number, width: number}) => {
                                return vlist({
                                    height: height - 62,
                                    width,
                                })
                            }}
                        </AutoSizer>
                    }
                </div>
            )}
        </>
    )
}
