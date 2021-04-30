import React, { useRef, useEffect, useState } from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { Col, Row, Input } from 'antd'
import { List } from 'antd'
import { DownOutlined, RightOutlined } from '@ant-design/icons'
import { ActionType, CohortType } from '~/types'
import { selectBoxLogic, searchItems } from 'lib/logic/selectBoxLogic'
import './SelectBox.scss'
import { selectBoxLogicType } from 'lib/logic/selectBoxLogicType'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import AutoSizer from 'react-virtualized/dist/commonjs/AutoSizer'
import VirtualizedList from 'react-virtualized/dist/commonjs/List'
import { ListRowProps, ListRowRenderer } from 'react-virtualized'

export interface SelectBoxItem {
    dataSource: SelectedItem[]
    renderInfo({ item }: { item: SelectedItem }): JSX.Element
    name: string
    header: (label: string) => JSX.Element
    type: string
    getValue: (item: SelectedItem) => string | number
    getLabel: (item: SelectedItem) => string
}

export interface SelectedItem {
    id?: number | string // Populated for actions (string is used for UUIDs)
    name: string
    key: string
    groupName?: string
    value?: string
    action?: ActionType
    volume_30_day?: number | null // Only for properties or events
    query_usage_30_day?: number | null // Only for properties or events
    is_numerical?: boolean // Only for properties
    category?: string
    cohort?: CohortType
}

const searchGroupItems = (items: SelectBoxItem[], search: string): SelectBoxItem[] => {
    const newItems: SelectBoxItem[] = []
    for (const item of items) {
        newItems.push({
            ...item,
            dataSource: searchItems(item.dataSource, search),
        })
    }
    return newItems
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
    const { selectedItem, selectedGroup, search } = useValues(dropdownLogic)
    const { setSearch, setSelectedItem, onKeyDown } = useActions(dropdownLogic)

    const deselect = (e: MouseEvent): void => {
        if (e.target && dropdownRef?.current?.contains(e.target as Node)) {
            return
        }
        onDismiss && onDismiss(e)
    }

    const data = !search ? items : searchGroupItems(items, search)

    useEffect(() => {
        if (selectedItemKey) {
            const allSources = data.map((item) => item.dataSource).flat()
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
                        style={{ width: '100%', borderRadius: 0, height: '10%' }}
                    />
                    <div style={{ width: '100%', height: '90%' }}>
                        <SelectUnit
                            items={Object.assign({}, ...data.map((item) => ({ [item.name]: item })))}
                            dropdownLogic={dropdownLogic}
                        />
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
    items,
}: {
    dropdownLogic: selectBoxLogicType<SelectedItem, SelectBoxItem> & BuiltLogic
    items: Record<string, SelectBoxItem>
}): JSX.Element {
    const { setSelectedItem, clickSelectedItem } = useActions(dropdownLogic)
    const { selectedItem, search, blockMouseOver } = useValues(dropdownLogic)
    const [hiddenData, setHiddenData] = useState<Record<string, SelectedItem[]>>({})
    const [data, setData] = useState<Record<string, SelectedItem[]>>({})
    const [flattenedData, setFlattenedData] = useState<SelectedItem[]>([])
    const [groupTypes, setGroupTypes] = useState<string[]>([])

    let lenghtOfData = 0
    Object.values(items).forEach((entry) => {
        lenghtOfData += entry.dataSource.length
    })

    useEffect(() => {
        const formattedData: Record<string, SelectedItem[]> = {}
        const _hiddenData: Record<string, SelectedItem[]> = {}
        const _groupTypes: string[] = []
        const currHidden = Object.keys(hiddenData)
        Object.keys(items).forEach((groupName) => {
            if (!currHidden.includes(groupName)) {
                formattedData[groupName] = items[groupName].dataSource
            } else {
                formattedData[groupName] = []
                _hiddenData[groupName] = items[groupName].dataSource
            }
            _groupTypes.push(groupName)
        })
        setGroupTypes(_groupTypes)
        setData(formattedData)
        setHiddenData(_hiddenData)
    }, [lenghtOfData])

    useEffect(() => {
        const _flattenedData: SelectedItem[] = []
        Object.keys(data).forEach((key) => {
            _flattenedData.push({
                key: key,
                name: key,
                groupName: key,
            })
            _flattenedData.push(...data[key].map((selectItem) => ({ ...selectItem, groupName: key })))
        })
        setFlattenedData(_flattenedData)
    }, [data])

    const hideKey = (key: string): void => {
        const { [`${key}`]: hideItem } = data
        const copy = {
            ...data,
        }
        copy[key] = []
        setData(copy)
        setHiddenData({
            ...hiddenData,
            [`${key}`]: hideItem,
        })
    }

    const showKey = (key: string): void => {
        const { [`${key}`]: showItem, ...restOfData } = hiddenData
        setHiddenData(restOfData)
        const copy = {
            ...data,
        }
        copy[key] = showItem
        setData(copy)
    }

    const renderItem: ListRowRenderer = ({ index, style }: ListRowProps) => {
        const item = flattenedData[index]

        if (!item.groupName) {
            return null
        }

        const group = items[item.groupName]
        if (groupTypes.includes(item.key)) {
            return (
                <div style={style} key={item.key}>
                    <span onClick={() => (hiddenData?.[item.key] ? showKey(item.key) : hideKey(item.key))}>
                        <h4 style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 12px', marginBottom: 0 }}>
                            {hiddenData?.[item.key] || !data[item.key].length ? <RightOutlined /> : <DownOutlined />}{' '}
                            {group.header(item.key)}
                            <span
                                style={{
                                    float: 'right',
                                    fontWeight: search && flattenedData.length > 0 ? 700 : 'normal',
                                }}
                                className="text-small"
                            >
                                {data?.[item.key]?.length || hiddenData?.[item.key]?.length || '0'}{' '}
                                {flattenedData.length === 1 ? 'entry' : 'entries'}
                            </span>
                        </h4>
                    </span>
                </div>
            )
        } else {
            return (
                <List.Item
                    className={selectedItem?.key === item.key ? 'selected' : undefined}
                    key={item.key}
                    onClick={() => clickSelectedItem(item, group)}
                    style={style}
                    onMouseOver={() =>
                        !blockMouseOver && setSelectedItem({ ...item, key: item.key, category: group.type })
                    }
                >
                    <PropertyKeyInfo value={item.name} />
                </List.Item>
            )
        }
    }

    return (
        <>
            {flattenedData.length > 0 && (
                <div style={{ height: '100%' }}>
                    {
                        <AutoSizer>
                            {({ height, width }: { height: number; width: number }) => {
                                return (
                                    <VirtualizedList
                                        height={height}
                                        overscanRowCount={0}
                                        rowCount={flattenedData.length}
                                        rowHeight={35}
                                        rowRenderer={renderItem}
                                        width={width}
                                    />
                                )
                            }}
                        </AutoSizer>
                    }
                </div>
            )}
        </>
    )
}
