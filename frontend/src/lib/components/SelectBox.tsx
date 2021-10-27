import React, { useRef, useEffect, useState } from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { Col, Row, Input } from 'antd'
import { List } from 'antd'
import { DownOutlined, RightOutlined } from '@ant-design/icons'
import { ActionType, CohortType } from '~/types'
import { selectBoxLogic } from 'lib/logic/selectBoxLogic'
import './SelectBox.scss'
import { selectBoxLogicType } from 'lib/logic/selectBoxLogicType'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import AutoSizer from 'react-virtualized/dist/commonjs/AutoSizer'
import VirtualizedList from 'react-virtualized/dist/commonjs/List'
import { ListRowProps, ListRowRenderer } from 'react-virtualized'

export interface SelectBoxItem {
    dataSource: SelectedItem[]
    renderInfo({ item }: { item: SelectedItem }): JSX.Element
    key: string
    name: string
    header: (label: string) => JSX.Element
    type: string
    getValue: (item: SelectedItem) => string | number
    getLabel: (item: SelectedItem) => string
    metadata?: Record<string, any> // Used to store additional data (e.g. search term)
}

interface CustomOnSelectProps {
    item: SelectedItem
    group: SelectBoxItem
}

export interface RenderInfoProps {
    item: SelectedItem
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
    onSelect?: (props?: CustomOnSelectProps) => void // Custom handler on item select
    onSelectPreventDefault?: boolean // Prevent default handler logic from running
    renderInfo?: (props?: RenderInfoProps) => JSX.Element // Override group renderInfo for this item
}

export function SelectBox({
    items,
    selectedItemKey,
    onSelect,
    onDismiss,
    inputPlaceholder,
    disablePopover = false,
}: {
    items: SelectBoxItem[]
    selectedItemKey?: string
    onSelect: (type: any, id: string | number, name: string) => void
    onDismiss: (event?: MouseEvent) => void
    inputPlaceholder?: string
    disablePopover?: boolean // Disable PropertyKeyInfo popover
}): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement>(null)
    const dropdownLogic = selectBoxLogic({ updateFilter: onSelect, items })
    const { selectedItem, selectedGroup, data } = useValues(dropdownLogic)
    const { setSearch, setSelectedItem, onKeyDown } = useActions(dropdownLogic)

    const deselect = (e: MouseEvent): void => {
        if (e.target && dropdownRef?.current?.contains(e.target as Node)) {
            return
        }
        onDismiss(e)
    }

    useEffect(() => {
        if (selectedItemKey) {
            const allSources = data.map((item) => item.dataSource).flat()
            setSelectedItem(allSources.filter((item) => item.key === selectedItemKey)[0] || null)
            const offset = document.querySelector<HTMLElement>(
                '.search-list [datakey="' + selectedItemKey + '"]'
            )?.offsetTop
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
        <div ref={dropdownRef} className="select-box" tabIndex={-1}>
            <Row style={{ height: '100%' }}>
                <Col sm={14} style={{ borderRight: '1px solid rgba(0, 0, 0, 0.1)', maxHeight: '100%' }}>
                    <Input
                        placeholder={inputPlaceholder || 'Search events'}
                        autoFocus
                        onChange={(e) => setSearch(e.target.value)}
                        onKeyDown={(e) => {
                            e.key === 'Tab' && onDismiss() // Close select box when input blurs via Tab
                        }}
                        style={{ width: '100%', borderRadius: 0, height: '10%' }}
                        data-attr="select-box-input"
                    />
                    <div style={{ width: '100%', height: '90%' }} tabIndex={-1}>
                        <SelectUnit
                            items={Object.assign({}, ...data.map((item) => ({ [item.name]: item })))}
                            dropdownLogic={dropdownLogic}
                            disablePopover={disablePopover}
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
    disablePopover = false,
}: {
    dropdownLogic: selectBoxLogicType & BuiltLogic
    items: Record<string, SelectBoxItem>
    disablePopover?: boolean // Disable PropertyKeyInfo popover
}): JSX.Element {
    const { setSelectedItem, clickSelectedItem } = useActions(dropdownLogic)
    const { selectedItem, search, blockMouseOver } = useValues(dropdownLogic)
    const [hiddenData, setHiddenData] = useState<Record<string, SelectedItem[]>>({})
    const [data, setData] = useState<Record<string, SelectedItem[]>>({})
    const [flattenedData, setFlattenedData] = useState<SelectedItem[]>([])
    const [groupTypes, setGroupTypes] = useState<string[]>([])

    let lengthOfData = 0
    Object.values(items).forEach((entry) => {
        lengthOfData += entry?.dataSource?.length || 0
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
    }, [lengthOfData])

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
                    data-attr={`select-item-${index}`}
                >
                    <PropertyKeyInfo value={item.name} disablePopover={disablePopover} />
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
                                        tabIndex={-1}
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
