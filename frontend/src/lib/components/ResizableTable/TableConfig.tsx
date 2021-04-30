import { Button, Card, Col, Row, Tooltip } from 'antd'
import React, { useEffect, useState } from 'react'
import { DownloadOutlined, SettingOutlined, SaveOutlined } from '@ant-design/icons'
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
    immutableColumns?: string[] // List of columns that cannot be removed
    onColumnUpdate?: (selectedColumns: string[]) => void
    saving?: boolean // Whether the saving routine is in process (i.e. loading indicators should be shown)
}

export function TableConfig({
    exportUrl,
    selectedColumns,
    availableColumns,
    immutableColumns,
    onColumnUpdate,
    saving,
}: TableConfigInterface): JSX.Element {
    const { state } = useValues(tableConfigLogic)
    const { setState } = useActions(tableConfigLogic)

    return (
        <>
            <div className="table-options">
                {selectedColumns && availableColumns && onColumnUpdate && (
                    <>
                        <Button
                            data-attr="events-table-column-selector"
                            onClick={() => setState('columnConfig')}
                            icon={<SettingOutlined />}
                        />
                        {state === 'columnConfig' && (
                            <ColumnConfigurator
                                allColumns={availableColumns}
                                currentSelection={selectedColumns}
                                immutableColumns={immutableColumns}
                                onClose={() => setState(null)}
                                onColumnUpdate={onColumnUpdate}
                                saving={saving}
                            />
                        )}
                    </>
                )}
                {exportUrl && (
                    <Tooltip title="Export up to 100,000 latest events.">
                        <Button icon={<DownloadOutlined />} href={exportUrl} />
                    </Tooltip>
                )}
            </div>
        </>
    )
}

interface ColumnConfiguratorInterface {
    currentSelection: string[] // List of currently selected columns
    allColumns: string[] // List of all possible columns
    immutableColumns?: string[]
    onClose: () => void
    onColumnUpdate: (selectedColumns: string[]) => void
    saving?: boolean
}

function ColumnConfigurator({
    currentSelection,
    allColumns,
    immutableColumns,
    onClose,
    onColumnUpdate,
    saving,
}: ColumnConfiguratorInterface): JSX.Element {
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
        const disabled = saving
        return (
            <div
                className={`column-display-item${disabled ? ' disabled' : ''}`}
                style={style}
                key={key}
                onClick={() => !disabled && selectColumn(selectableColumns[index])}
            >
                <Checkbox style={{ marginRight: 8 }} checked={false} disabled={disabled} />
                {<PropertyKeyInfo value={selectableColumns[index]} />}
            </div>
        )
    }

    function RenderSelectedColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = immutableColumns?.includes(selectedColumns[index]) || saving
        return (
            <div
                className={`column-display-item${disabled ? ' disabled' : ''}`}
                style={style}
                key={key}
                onClick={() => !disabled && unSelectColumn(selectedColumns[index])}
            >
                <Checkbox style={{ marginRight: 8 }} checked disabled={disabled} />
                {<PropertyKeyInfo value={selectedColumns[index]} />}
            </div>
        )
    }

    return (
        <Modal
            centered
            visible
            title="Toggle column visibility"
            confirmLoading={saving}
            onOk={() => onColumnUpdate(selectedColumns)}
            width={700}
            className="column-configurator-modal"
            okButtonProps={{
                // @ts-ignore
                'data-attr': 'items-selector-confirm',
                loading: saving,
                icon: <SaveOutlined />,
            }}
            okText="Save preferences"
            onCancel={onClose}
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
