import { Button, Card, Col, Input, Row } from 'antd'
import React, { useEffect, useState } from 'react'
import { DownloadOutlined, SettingOutlined, SaveOutlined, SearchOutlined, ClearOutlined } from '@ant-design/icons'
import './TableConfig.scss'
import { useActions, useValues } from 'kea'
import { tableConfigLogic } from './tableConfigLogic'
import Modal from 'antd/lib/modal/Modal'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import Fuse from 'fuse.js'
import { Tooltip } from 'lib/components/Tooltip'

interface TableConfigInterface {
    exportUrl?: string
    selectedColumns?: string[] // Allows column visibility customization
    availableColumns?: string[] // List of all available columns (should include selectedColumns too for simplicity)
    immutableColumns?: string[] // List of columns that cannot be removed
    defaultColumns?: string[] // To enable resetting to default
    onColumnUpdate?: (selectedColumns: string[]) => void
    saving?: boolean // Whether the saving routine is in process (i.e. loading indicators should be shown)
    mainActionComponent?: JSX.Element
}

export function TableConfig({
    exportUrl,
    selectedColumns,
    availableColumns,
    onColumnUpdate,
    mainActionComponent,
    ...props
}: TableConfigInterface): JSX.Element {
    const { state } = useValues(tableConfigLogic)
    const { setState } = useActions(tableConfigLogic)

    return (
        <>
            <div className="table-options">
                <div className="main-actions">{mainActionComponent}</div>
                <div className="rhs-actions">
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
                                    onClose={() => setState(null)}
                                    onColumnUpdate={onColumnUpdate}
                                    {...props}
                                />
                            )}
                        </>
                    )}
                    {exportUrl && (
                        <Tooltip title="Export up to 100,000 latest events." placement="left">
                            <Button icon={<DownloadOutlined />} href={exportUrl} />
                        </Tooltip>
                    )}
                </div>
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
    defaultColumns?: string[]
}

function ColumnConfigurator({
    currentSelection,
    allColumns,
    immutableColumns,
    onClose,
    onColumnUpdate,
    saving,
    defaultColumns,
}: ColumnConfiguratorInterface): JSX.Element {
    const [selectableColumns, setSelectableColumns] = useState([] as string[]) // Stores the actual state of columns that could be selected
    const [selectedColumns, setSelectedColumns] = useState([] as string[]) // Stores the actual state of columns that **are** selected
    const [scrollSelectedToIndex, setScrollSelectedToIndex] = useState(0)
    const [searchTerm, setSearchTerm] = useState('')

    const selectedColumnsDisplay = searchTerm
        ? new Fuse(selectedColumns, {
              threshold: 0.3,
          })
              .search(searchTerm)
              .map(({ item }) => item)
        : selectedColumns

    const selectableColumnsDisplay = searchTerm
        ? new Fuse(selectableColumns, {
              threshold: 0.3,
          })
              .search(searchTerm)
              .map(({ item }) => item)
        : selectableColumns

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

    function RenderAvailableColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = saving
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

    function RenderSelectedColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = immutableColumns?.includes(selectedColumnsDisplay[index]) || saving

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
                <Col sm={11}>
                    <Card>
                        <h3 className="l3">Available columns</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={selectableColumnsDisplay.length}
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
                                            rowCount={selectedColumnsDisplay.length}
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
