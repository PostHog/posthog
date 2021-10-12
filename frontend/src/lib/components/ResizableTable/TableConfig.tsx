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
import clsx from 'clsx'

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
    const { showModal } = useActions(tableConfigLogic)

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
    // the virtualised list doesn't support gaps between items in the list
    // setting the container to be larger than we need
    // and adding a container with a smaller height to each row item
    // allows the new row item to set a margin around itself
    const rowContainerHeight = 36
    const rowItemHeight = 32

    const [selectableColumns, setSelectableColumns] = useState([] as string[]) // Stores the actual state of columns that could be selected
    const [userColumnSelection, setUserColumnSelection] = useState([] as string[]) // Stores the actual state of columns that **are** selected
    const [scrollSelectedToIndex, setScrollSelectedToIndex] = useState(0)
    const [searchTerm, setSearchTerm] = useState('')

    const selectedColumnsDisplay = searchFilteredColumns(searchTerm, userColumnSelection)

    const selectableColumnsDisplay = searchFilteredColumns(searchTerm, selectableColumns)

    const { selectedColumns } = useValues(tableConfigLogic)
    const { setSelectedColumns, hideModal } = useActions(tableConfigLogic)

    const currentSelection = selectedColumns === 'DEFAULT' ? defaultColumns : selectedColumns

    useEffect(() => {
        setUserColumnSelection(currentSelection)
        setSelectableColumns(allColumns.filter((column) => !currentSelection.includes(column)))
    }, [currentSelection, allColumns])

    const selectColumn = (column: string): void => {
        setUserColumnSelection([...userColumnSelection, column])
        setSelectableColumns(selectableColumns.filter((item) => item != column))
        setScrollSelectedToIndex(userColumnSelection.length)
    }

    const unSelectColumn = (column: string): void => {
        setUserColumnSelection(userColumnSelection.filter((item) => item != column))
        setSelectableColumns([...selectableColumns, column])
    }

    const resetColumns = (): void => {
        if (defaultColumns) {
            setUserColumnSelection(defaultColumns)
            setSelectableColumns(allColumns.filter((column) => !currentSelection.includes(column)))
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
                    className={clsx(['column-display-item', 'selected', { disabled: disabled }])}
                    style={{ height: `${rowItemHeight}px` }}
                >
                    <Checkbox style={{ marginRight: 8 }} checked disabled={disabled} />
                    {<PropertyKeyInfo value={selectedColumnsDisplay[index]} />}
                </div>
            </div>
        )
    }

    return (
        <Modal
            centered
            visible
            title="Configure columns"
            onOk={() => setSelectedColumns(userColumnSelection)}
            width={700}
            className="column-configurator-modal"
            okButtonProps={{
                // @ts-ignore
                'data-attr': 'items-selector-confirm',
                icon: <SaveOutlined />,
            }}
            okText="Save"
            onCancel={hideModal}
        >
            {defaultColumns && (
                <Row>
                    <Col xs={24} className="mb">
                        <div className={'text-right'}>
                            <Button
                                type="link"
                                icon={<ClearOutlined />}
                                style={{ paddingRight: 0 }}
                                onClick={resetColumns}
                            >
                                Reset to default
                            </Button>
                        </div>
                    </Col>
                </Row>
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
                    <Card>
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
