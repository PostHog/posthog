import { Button, Card, Col, Row, Tooltip } from 'antd'
import React, { useEffect, useState } from 'react'
import { DownloadOutlined, SettingOutlined } from '@ant-design/icons'
import './TableConfig.scss'
import { useActions, useValues } from 'kea'
import { tableConfigLogic } from './tableConfigLogic'
import Modal from 'antd/lib/modal/Modal'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import Checkbox from 'antd/lib/checkbox/Checkbox'

interface TableConfigInterface {
    exportUrl?: string
    selectedColumns?: string[] // Allows column visibility customization
    availableColumns?: string[] // List of all available columns (should include selectedColumns too for simplicity)
    onColumnUpdate?: (selectedColumns: string[]) => void
}

export function TableConfig({
    exportUrl,
    selectedColumns,
    availableColumns,
}: // onColumnUpdate,
TableConfigInterface): JSX.Element {
    const { state } = useValues(tableConfigLogic)
    const { setState } = useActions(tableConfigLogic)
    return (
        <>
            <div className="table-options">
                {selectedColumns && availableColumns && (
                    <Button
                        data-attr="events-table-column-selector"
                        onClick={() => setState('columnConfig')}
                        icon={<SettingOutlined />}
                    />
                )}
                {exportUrl && (
                    <Tooltip title="Export up to 100,000 latest events.">
                        <Button icon={<DownloadOutlined />} href={exportUrl} />
                    </Tooltip>
                )}
            </div>
            {selectedColumns && availableColumns && state === 'columnConfig' && (
                <ColumnConfigurator allColumns={availableColumns} currentSelection={selectedColumns} />
            )}
        </>
    )
}

interface ColumnConfiguratorInterface {
    currentSelection: string[] // List of currently selected columns
    allColumns: string[] // List of all possible columns
}

function ColumnConfigurator({ currentSelection, allColumns }: ColumnConfiguratorInterface): JSX.Element {
    const [selectableColumns, setSelectableColumns] = useState([] as string[])
    const [selectedColumns, setSelectedColumns] = useState([] as string[])
    const [scrollSelectedToIndex, setScrollSelectedToIndex] = useState(0)

    useEffect(() => {
        setSelectedColumns(currentSelection)
        setSelectableColumns(allColumns.filter((column) => !selectedColumns.includes(column)))
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

    function RenderAvailableColumn({ index, style, key }: ListRowProps): JSX.Element {
        return (
            <div
                className="column-display-item"
                style={style}
                key={key}
                onClick={() => selectColumn(selectableColumns[index])}
            >
                <Checkbox style={{ marginRight: 8 }} checked={false} />
                {<PropertyKeyInfo value={selectableColumns[index]} />}
            </div>
        )
    }

    function RenderSelectedColumn({ index, style, key }: ListRowProps): JSX.Element {
        return (
            <div
                className="column-display-item"
                style={style}
                key={key}
                onClick={() => unSelectColumn(selectedColumns[index])}
            >
                <Checkbox style={{ marginRight: 8 }} checked />
                {<PropertyKeyInfo value={selectedColumns[index]} />}
            </div>
        )
    }

    return (
        <Modal
            centered
            visible
            title="Toggle column visibility"
            /*onOk={_onConfirm}
            confirmLoading={!loaded}*/
            width={700}
            className="column-configurator-modal"
            okButtonProps={{
                className: 'items-selector-confirm',
            }}
        >
            <Row gutter={16}>
                <Col sm={11}>
                    <Card>
                        <h3 className="l3">Available columns</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={selectableColumns.length}
                                            rowRenderer={RenderAvailableColumn}
                                            rowHeight={32}
                                            width={width}
                                        />
                                    )
                                }}
                            </AutoSizer>
                        </div>
                    </Card>
                </Col>
                <Col sm={2} />
                <Col sm={11}>
                    <Card>
                        <h3 className="l3">Visible columns</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={selectedColumns.length}
                                            rowRenderer={RenderSelectedColumn}
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
