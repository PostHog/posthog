import React, { useRef, useEffect, useState } from 'react'
import { kea, useActions, useValues } from 'kea'
import { Col, Row, Input, Divider } from 'antd'
import { actionFilterDropdownLogicType } from 'types/scenes/insights/ActionFilter/ActionFilterDropdownType'
import { List } from 'antd'
import { DownOutlined, RightOutlined } from '@ant-design/icons'
import { EntityTypes } from '../../scenes/insights/trendsLogic'
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

export const actionFilterDropdownLogic = kea({
    actions: {
        setSelectedEvent: (event: SelectedItem) => ({ event }),
        setSearch: (search: string) => ({ search }),
        clickSelectedEvent: (event: SelectedItem) => ({ event }),
    },
    reducers: {
        selectedEvent: [
            false,
            {
                setSelectedEvent: (_, { event }: { event: SelectedItem }) => event,
            },
        ],
        search: [
            false,
            {
                setSearch: (_, { search }: { search: string }) => search,
            },
        ],
    },
    listeners: ({ props }) => ({
        clickSelectedEvent: ({ event }) => {
            if (event.event) {
                props.updateFilter(EntityTypes.EVENTS, event.event, event.event)
            } else {
                props.updateFilter(EntityTypes.ACTIONS, event.action.id, event.action.name)
            }
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
    const dropdownLogic = actionFilterDropdownLogic({ updateFilter: onSelect })
    const { selectedEvent } = useValues(dropdownLogic)
    const { setSearch, setSelectedEvent } = useActions(dropdownLogic)

    let RenderInfo
    if (selectedEvent.key) {
        RenderInfo = items.filter(
            (item) => item.dataSource.filter((item) => item.key === selectedEvent.key).length > 0
        )[0].renderInfo
    }

    const deselect = (e): void => {
        if (dropdownRef.current.contains(e.target)) {
            return
        }
        onDismiss && onDismiss(e)
    }

    useEffect(() => {
        if (selectedItemKey) {
            const allSources = items.map((item) => item.dataSource).flat()
            setSelectedEvent(allSources.filter((item) => item.key === selectedItemKey)[0] || false)
            const offset = document.querySelector('.action-filter-dropdown [datakey="' + selectedItemKey + '"]')
                ?.offsetTop
            document.querySelector('.search-list').scrollTop = offset
        }
        document.addEventListener('mousedown', deselect)
        return () => {
            document.removeEventListener('mousedown', deselect)
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
                    {RenderInfo && <RenderInfo item={selectedEvent} />}
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
    const { setSelectedEvent, clickSelectedEvent } = useActions(dropdownLogic)
    const { selectedEvent, search } = useValues(dropdownLogic)
    const data = dataSource.filter((item) => !search || item.name.toLowerCase().indexOf(search.toLowerCase()) > -1)
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
                            className={selectedEvent.key === item.key && 'selected'}
                            dataKey={item.key}
                            onClick={() => clickSelectedEvent(item)}
                            onMouseOver={() => setSelectedEvent({ ...item, key: item.key, category: name })}
                        >
                            {item.name}
                        </List.Item>
                    )}
                />
            )}
        </>
    )
}
