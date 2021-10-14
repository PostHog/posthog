import { Button, Card, Col, Input, Row, Space } from 'antd'
import React, { useEffect, useState } from 'react'
import { ControlOutlined, LockOutlined, SearchOutlined } from '@ant-design/icons'
import './TableConfig.scss'
import { useActions, useValues } from 'kea'
import { tableConfigLogic } from './tableConfigLogic'
import Modal from 'antd/lib/modal/Modal'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import Fuse from 'fuse.js'
import clsx from 'clsx'
import { Tooltip } from 'lib/components/Tooltip'

interface TableConfigProps {
    availableColumns: string[]
    immutableColumns?: string[]
    defaultColumns: string[]
}

/**
 * A scene that contains a ResizableTable with many possible columns
 * can use this to let the user choose which columns they see
 *
 * @param availableColumns the full set of column titles in the table's data
 * @param immutableColumns the titles of the columns that are always displayed
 * @param defaultColumns the titles of the set of columns to show when there is no user choice
 * @constructor
 */
export function TableConfig({ availableColumns, immutableColumns, defaultColumns }: TableConfigProps): JSX.Element {
    const { modalVisible } = useValues(tableConfigLogic)
    const { showModal, setDefaultColumns, setAllPossibleColumns } = useActions(tableConfigLogic)

    useEffect(() => {
        setDefaultColumns(defaultColumns)
        setAllPossibleColumns(availableColumns)
    }, [])

    return (
        <>
            <div className="table-options">
                <div className="rhs-actions">
                    <Space align="baseline">
                        <>
                            <Button
                                data-attr="events-table-column-selector"
                                onClick={showModal}
                                icon={<ControlOutlined rotate={90} />}
                            >
                                Configure Columns
                            </Button>
                            {modalVisible && (
                                <ColumnConfigurator
                                    immutableColumns={immutableColumns}
                                    defaultColumns={defaultColumns}
                                />
                            )}
                        </>
                    </Space>
                </div>
            </div>
        </>
    )
}

const searchFilteredColumns = (searchTerm: string, columns: string[]): string[] =>
    searchTerm
        ? new Fuse(columns, {
              threshold: 0.3,
          })
              .search(searchTerm)
              .map(({ item }) => item)
        : columns

interface ColumnConfiguratorInterface {
    immutableColumns?: string[]
    defaultColumns: string[]
}

function ColumnConfigurator({ immutableColumns, defaultColumns }: ColumnConfiguratorInterface): JSX.Element {
    // the virtualised list doesn't support gaps between items in the list
    // setting the container to be larger than we need
    // and adding a container with a smaller height to each row item
    // allows the new row item to set a margin around itself
    const rowContainerHeight = 36
    const rowItemHeight = 32

    const { usersUnsavedSelection, selectableColumns } = useValues(tableConfigLogic)
    const { setSelectedColumns, hideModal, setUsersUnsavedSelection } = useActions(tableConfigLogic)

    const [scrollSelectedToIndex, setScrollSelectedToIndex] = useState(0)

    const [searchTerm, setSearchTerm] = useState('')

    const selectedColumnsDisplay = searchFilteredColumns(searchTerm, usersUnsavedSelection)

    const selectableColumnsDisplay = searchFilteredColumns(searchTerm, selectableColumns)

    const selectColumn = (column: string): void => {
        setUsersUnsavedSelection([...usersUnsavedSelection, column])
        setScrollSelectedToIndex(usersUnsavedSelection.length)
    }

    const unSelectColumn = (column: string): void => {
        setUsersUnsavedSelection(usersUnsavedSelection.filter((item) => item != column))
    }

    const resetColumns = (): void => {
        if (defaultColumns) {
            setUsersUnsavedSelection(defaultColumns)
        }
    }

    function AvailableColumn({ index, style, key }: ListRowProps): JSX.Element {
        return (
            <div style={style} key={key} onClick={() => selectColumn(selectableColumnsDisplay[index])}>
                <div className={'column-display-item'} style={{ height: `${rowItemHeight}px` }}>
                    <Checkbox style={{ marginRight: 8 }} checked={false} />
                    {<PropertyKeyInfo value={selectableColumnsDisplay[index]} />}
                </div>
            </div>
        )
    }

    function SelectedColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = immutableColumns?.includes(selectedColumnsDisplay[index])

        return (
            <div style={style} key={key} onClick={() => !disabled && unSelectColumn(selectedColumnsDisplay[index])}>
                <div
                    className={clsx(['column-display-item', { selected: !disabled, disabled: disabled }])}
                    style={{ height: `${rowItemHeight}px` }}
                >
                    <Checkbox style={{ marginRight: 8 }} checked disabled={disabled} />
                    {<PropertyKeyInfo value={selectedColumnsDisplay[index]} />}
                    {disabled && (
                        <div className={'text-right'} style={{ flex: 1 }}>
                            <Tooltip title={'Reserved'}>
                                <LockOutlined />
                            </Tooltip>
                        </div>
                    )}
                </div>
            </div>
        )
    }

    return (
        <Modal
            centered
            visible
            title="Configure columns"
            onOk={() => setSelectedColumns(usersUnsavedSelection)}
            width={700}
            bodyStyle={{ padding: '16px 16px 0 16px' }}
            className="column-configurator-modal"
            okButtonProps={{
                // @ts-ignore
                'data-attr': 'items-selector-confirm',
            }}
            okText="Save"
            onCancel={hideModal}
            footer={
                <Row>
                    <Col flex={0}>
                        <Button className={'text-blue'} onClick={resetColumns}>
                            Reset to default
                        </Button>
                    </Col>
                    <Col flex={1}>&nbsp;</Col>
                    <Col flex={0}>
                        <Button className={'text-blue'} type="text" onClick={hideModal}>
                            Cancel
                        </Button>
                    </Col>
                    <Col flex={0}>
                        <Button type="primary" onClick={() => setSelectedColumns(usersUnsavedSelection)}>
                            Save
                        </Button>
                    </Col>
                </Row>
            }
        >
            <Input
                allowClear
                autoFocus
                placeholder="Search"
                prefix={<SearchOutlined />}
                style={{ paddingLeft: '7px' }} // the prefix has 11px to the left but only 4 to the right
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
            />
            <Row gutter={16} className="mt">
                <Col xs={24} sm={11}>
                    <Card bordered={false}>
                        <h3 className="l3">Hidden columns ({selectableColumnsDisplay.length})</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={selectableColumnsDisplay.length}
                                            rowRenderer={AvailableColumn}
                                            rowHeight={rowContainerHeight}
                                            width={width}
                                        />
                                    )
                                }}
                            </AutoSizer>
                        </div>
                    </Card>
                </Col>
                <Col xs={0} sm={2} />
                <Col xs={24} sm={11}>
                    <Card bordered={false}>
                        <h3 className="l3">Visible columns ({selectedColumnsDisplay.length})</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={selectedColumnsDisplay.length}
                                            rowRenderer={SelectedColumn}
                                            rowHeight={rowContainerHeight}
                                            width={width}
                                            scrollToIndex={scrollSelectedToIndex}
                                        />
                                    )
                                }}
                            </AutoSizer>
                        </div>
                    </Card>
                </Col>
            </Row>
        </Modal>
    )
}
