import { Button, Card, Col, Input, Row, Space } from 'antd'
import React from 'react'
import { ControlOutlined, LockOutlined, SearchOutlined } from '@ant-design/icons'
import './TableConfig.scss'
import { useActions, useValues } from 'kea'
import { tableConfigLogic } from './tableConfigLogic'
import Modal from 'antd/lib/modal/Modal'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/commonjs/List'
import { AutoSizer } from 'react-virtualized'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import clsx from 'clsx'
import { Tooltip } from 'lib/components/Tooltip'
import { columnConfiguratorLogic } from 'lib/components/ResizableTable/columnConfiguratorLogic'

interface TableConfigProps {
    availableColumns: string[] //the full set of column titles in the table's data
    immutableColumns?: string[] //the titles of the columns that are always displayed
    defaultColumns: string[] // the titles of the set of columns to show when there is no user choice
}

/**
 * A scene that contains a ResizableTable with many possible columns
 * can use this to let the user choose which columns they see
 */
export function TableConfig(props: TableConfigProps): JSX.Element {
    const { showModal } = useActions(tableConfigLogic)
    const { modalVisible } = useValues(tableConfigLogic)

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
                                    immutableColumns={props.immutableColumns}
                                    availableColumns={props.availableColumns}
                                    defaultColumns={props.defaultColumns}
                                />
                            )}
                        </>
                    </Space>
                </div>
            </div>
        </>
    )
}

function ColumnConfigurator({ immutableColumns, defaultColumns, availableColumns }: TableConfigProps): JSX.Element {
    // the virtualised list doesn't support gaps between items in the list
    // setting the container to be larger than we need
    // and adding a container with a smaller height to each row item
    // allows the new row item to set a margin around itself
    const rowContainerHeight = 36
    const rowItemHeight = 32

    const { selectedColumns } = useValues(tableConfigLogic)
    const { hideModal } = useActions(tableConfigLogic)

    const logic = columnConfiguratorLogic({
        availableColumns,
        selectedColumns: selectedColumns === 'DEFAULT' ? defaultColumns : selectedColumns,
    })
    const { selectColumn, unselectColumn, resetColumns, save, setColumnFilter } = useActions(logic)
    const { visibleColumns, hiddenColumns, scrollIndex, columnFilter, filteredVisibleColumns, filteredHiddenColumns } =
        useValues(logic)

    function AvailableColumn({ index, style, key }: ListRowProps): JSX.Element {
        return (
            <div style={style} key={key} onClick={() => selectColumn(filteredHiddenColumns[index])}>
                <div className={'column-display-item'} style={{ height: `${rowItemHeight}px` }}>
                    <Checkbox style={{ marginRight: 8 }} checked={false} />
                    {<PropertyKeyInfo value={filteredHiddenColumns[index]} />}
                </div>
            </div>
        )
    }

    function SelectedColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = immutableColumns?.includes(filteredVisibleColumns[index])

        return (
            <div style={style} key={key} onClick={() => !disabled && unselectColumn(filteredVisibleColumns[index])}>
                <div
                    className={clsx(['column-display-item', { selected: !disabled, disabled: disabled }])}
                    style={{ height: `${rowItemHeight}px` }}
                >
                    <Checkbox style={{ marginRight: 8 }} checked disabled={disabled} />
                    {<PropertyKeyInfo value={filteredVisibleColumns[index]} />}
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
            onOk={save}
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
                        <Button className={'text-blue'} onClick={() => resetColumns(defaultColumns)}>
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
                        <Button type="primary" onClick={save}>
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
                value={columnFilter}
                onChange={(e) => setColumnFilter(e.target.value)}
            />
            <Row gutter={16} className="mt">
                <Col xs={24} sm={11}>
                    <Card bordered={false}>
                        <h3 className="l3">Hidden columns ({hiddenColumns.length})</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={filteredHiddenColumns.length}
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
                        <h3 className="l3">Visible columns ({visibleColumns.length})</h3>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <VirtualizedList
                                            height={height}
                                            rowCount={filteredVisibleColumns.length}
                                            rowRenderer={SelectedColumn}
                                            rowHeight={rowContainerHeight}
                                            width={width}
                                            scrollToIndex={scrollIndex}
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
