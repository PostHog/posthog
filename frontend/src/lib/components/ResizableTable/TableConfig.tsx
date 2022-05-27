import { Button, Col, Row, Space } from 'antd'
import React from 'react'
import { ControlOutlined, LockOutlined, CloseOutlined } from '@ant-design/icons'
import './TableConfig.scss'
import { useActions, useValues } from 'kea'
import { tableConfigLogic } from './tableConfigLogic'
import Modal from 'antd/lib/modal/Modal'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/es/List'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import clsx from 'clsx'
import { Tooltip } from 'lib/components/Tooltip'
import { columnConfiguratorLogic } from 'lib/components/ResizableTable/columnConfiguratorLogic'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/components/LemonButton'
import { IconTuning } from 'lib/components/icons'

interface TableConfigProps {
    immutableColumns?: string[] //the titles of the columns that are always displayed
    defaultColumns: string[] // the titles of the set of columns to show when there is no user choice
}

/**
 * A scene that contains a ResizableTable with many possible columns
 * can use this to let the user choose which columns they see
 */
export function TableConfig(props: TableConfigProps): JSX.Element {
    const { showModal } = useActions(tableConfigLogic)

    return (
        <>
            <Button data-attr="events-table-column-selector" onClick={showModal} icon={<ControlOutlined rotate={90} />}>
                Customize columns
            </Button>
            <ColumnConfigurator immutableColumns={props.immutableColumns} defaultColumns={props.defaultColumns} />
        </>
    )
}

export function LemonTableConfig(props: TableConfigProps): JSX.Element {
    const { showModal } = useActions(tableConfigLogic)

    return (
        <>
            <LemonButton
                type="secondary"
                data-attr="events-table-column-selector"
                onClick={showModal}
                icon={<IconTuning style={{ color: 'var(--primary)' }} />}
            >
                Customize columns
            </LemonButton>
            <ColumnConfigurator immutableColumns={props.immutableColumns} defaultColumns={props.defaultColumns} />
        </>
    )
}

function ColumnConfigurator({ immutableColumns, defaultColumns }: TableConfigProps): JSX.Element {
    // the virtualised list doesn't support gaps between items in the list
    // setting the container to be larger than we need
    // and adding a container with a smaller height to each row item
    // allows the new row item to set a margin around itself
    const rowContainerHeight = 36
    const rowItemHeight = 32

    const { selectedColumns: currentlySelectedColumns, modalVisible } = useValues(tableConfigLogic)
    const { hideModal } = useActions(tableConfigLogic)

    const logic = columnConfiguratorLogic({
        selectedColumns: currentlySelectedColumns === 'DEFAULT' ? defaultColumns : currentlySelectedColumns,
    })
    const { selectColumn, unselectColumn, resetColumns, save } = useActions(logic)
    const { selectedColumns } = useValues(logic)

    function SelectedColumn({ index, style, key }: ListRowProps): JSX.Element {
        const disabled = immutableColumns?.includes(selectedColumns[index])

        return (
            <div style={style} key={key} onClick={() => !disabled && unselectColumn(selectedColumns[index])}>
                <div
                    className={clsx(['column-display-item', { selected: !disabled, disabled: disabled }])}
                    style={{ height: `${rowItemHeight}px` }}
                >
                    <PropertyKeyInfo value={selectedColumns[index]} />
                    <div className="text-right" style={{ flex: 1 }}>
                        <Tooltip title={disabled ? 'Reserved' : 'Remove'}>
                            {disabled ? <LockOutlined /> : <CloseOutlined style={{ color: 'var(--danger)' }} />}
                        </Tooltip>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <Modal
            centered
            visible={modalVisible}
            title="Customize columns"
            onOk={save}
            width={700}
            bodyStyle={{ padding: '16px 16px 0 16px' }}
            className="column-configurator-modal"
            okButtonProps={{
                // @ts-expect-error
                'data-attr': 'items-selector-confirm',
            }}
            okText="Save"
            onCancel={hideModal}
            footer={
                <Row>
                    <Space style={{ flexGrow: 1 }} align="start">
                        <Button className="text-blue" onClick={() => resetColumns(defaultColumns)}>
                            Reset to default
                        </Button>
                    </Space>
                    <Space>
                        <Button className="text-blue" type="text" onClick={hideModal}>
                            Cancel
                        </Button>
                        <Button type="primary" onClick={save}>
                            Save
                        </Button>
                    </Space>
                </Row>
            }
        >
            <Row gutter={16} className="mt">
                <Col xs={24} sm={12}>
                    <h3 className="l3">Available columns</h3>
                    <div style={{ height: 320 }}>
                        <AutoSizer>
                            {({ height, width }: { height: number; width: number }) => {
                                return (
                                    <TaxonomicFilter
                                        height={height}
                                        width={width}
                                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                        value={undefined}
                                        onChange={(_, value) => value && selectColumn(String(value))}
                                        popoverEnabled={false}
                                        selectFirstItem={false}
                                    />
                                )
                            }}
                        </AutoSizer>
                    </div>
                </Col>
                <Col xs={24} sm={12}>
                    <h3 className="l3">Visible columns ({selectedColumns.length})</h3>
                    <div style={{ height: 320 }}>
                        <AutoSizer>
                            {({ height, width }: { height: number; width: number }) => {
                                return (
                                    <VirtualizedList
                                        height={height}
                                        rowCount={selectedColumns.length}
                                        rowRenderer={SelectedColumn}
                                        rowHeight={rowContainerHeight}
                                        width={width}
                                    />
                                )
                            }}
                        </AutoSizer>
                    </div>
                </Col>
            </Row>
        </Modal>
    )
}
