import { Button, Card, Col, Input, Row, Space } from 'antd'
import React, { useEffect, useState } from 'react'
import { ControlOutlined, SaveOutlined, SearchOutlined, ClearOutlined } from '@ant-design/icons'
import './TableConfig.scss'
import { useActions, useValues } from 'kea'
import { tableConfigLogic } from './tableConfigLogic'
import Modal from 'antd/lib/modal/Modal'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import Fuse from 'fuse.js'

interface TableConfigInterface {
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
export function TableConfig({ availableColumns, immutableColumns, defaultColumns }: TableConfigInterface): JSX.Element {
    const { modalVisible } = useValues(tableConfigLogic)
    const { setModalVisible } = useActions(tableConfigLogic)

    return (
        <>
            <div className="table-options">
                <div className="rhs-actions">
                    <Space align="baseline">
                        <>
                            <Button
                                data-attr="events-table-column-selector"
                                onClick={() => setModalVisible(true)}
                                icon={<ControlOutlined rotate={90} />}
                            >
                                Configure Columns
                            </Button>
                            {modalVisible && (
                                <ColumnConfigurator
                                    allColumns={availableColumns}
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
    allColumns: string[] // List of all possible columns
    immutableColumns?: string[]
    defaultColumns: string[]
}

function ColumnConfigurator({
    allColumns,
    immutableColumns,
    defaultColumns,
}: ColumnConfiguratorInterface): JSX.Element {
    const [selectableColumns, setSelectableColumns] = useState([] as string[]) // Stores the actual state of columns that could be selected
    const [selectedColumns, setSelectedColumns] = useState([] as string[]) // Stores the actual state of columns that **are** selected
    const [scrollSelectedToIndex, setScrollSelectedToIndex] = useState(0)
    const [searchTerm, setSearchTerm] = useState('')

    const selectedColumnsDisplay = searchFilteredColumns(searchTerm, selectedColumns)

    const selectableColumnsDisplay = searchFilteredColumns(searchTerm, selectableColumns)

    const { columnConfigSaving, columnConfig } = useValues(tableConfigLogic)
    const { setColumnConfig, setModalVisible } = useActions(tableConfigLogic)

    const currentSelection = columnConfig === 'DEFAULT' ? defaultColumns : columnConfig

    useEffect(() => {
        setSelectedColumns(currentSelection)
        setSelectableColumns(allColumns.filter((column) => !currentSelection.includes(column)))
    }, [currentSelection, allColumns])

    const selectColumn = (column: string): void => {
        setSelectedColumns([...selectedColumns, column])
        setSelectableColumns(selectableColumns.filter((item) => item != column))
        setScrollSelectedToIndex(selectedColumns.length)
    }

    const unSelectColumn = (column: string): void => {
        setSelectedColumns(selectedColumns.filter((item) => item != column))
        setSelectableColumns([...selectableColumns, column])
    }

    const resetColumns = (): void => {
        if (defaultColumns) {
            setSelectedColumns(defaultColumns)
            setSelectableColumns(allColumns.filter((column) => !currentSelection.includes(column)))
        }
    }

    function AvailableColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = columnConfigSaving
        return (
            <div
                className={`column-display-item${disabled ? ' disabled' : ''}`}
                style={style}
                key={key}
                onClick={() => !disabled && selectColumn(selectableColumnsDisplay[index])}
            >
                <Checkbox style={{ marginRight: 8 }} checked={false} disabled={disabled} />
                {<PropertyKeyInfo value={selectableColumnsDisplay[index]} />}
            </div>
        )
    }

    function SelectedColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = immutableColumns?.includes(selectedColumnsDisplay[index]) || columnConfigSaving

        return (
            <div
                className={`column-display-item${disabled ? ' disabled' : ''}`}
                style={style}
                key={key}
                onClick={() => !disabled && unSelectColumn(selectedColumnsDisplay[index])}
            >
                <Checkbox style={{ marginRight: 8 }} checked disabled={disabled} />
                {<PropertyKeyInfo value={selectedColumnsDisplay[index]} />}
            </div>
        )
    }

    return (
        <Modal
            centered
            visible
            title="Toggle column visibility"
            confirmLoading={columnConfigSaving}
            onOk={() => setColumnConfig(selectedColumns)}
            width={700}
            className="column-configurator-modal"
            okButtonProps={{
                // @ts-ignore
                'data-attr': 'items-selector-confirm',
                loading: columnConfigSaving,
                icon: <SaveOutlined />,
            }}
            okText="Save preferences"
            onCancel={() => setModalVisible(false)}
        >
            {defaultColumns && (
                <div className="text-right mb">
                    <Button type="link" icon={<ClearOutlined />} style={{ paddingRight: 0 }} onClick={resetColumns}>
                        Reset to default
                    </Button>
                </div>
            )}
            <Input
                allowClear
                autoFocus
                placeholder="Search for a column ..."
                addonAfter={<SearchOutlined />}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
            />
            <Row gutter={16} className="mt">
                <Col xs={24} sm={11}>
                    <Card>
                        <h3 className="l3">Available columns</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={selectableColumnsDisplay.length}
                                            rowRenderer={AvailableColumn}
                                            rowHeight={32}
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
                    <Card>
                        <h3 className="l3">Visible columns</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={selectedColumnsDisplay.length}
                                            rowRenderer={SelectedColumn}
                                            rowHeight={32}
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
