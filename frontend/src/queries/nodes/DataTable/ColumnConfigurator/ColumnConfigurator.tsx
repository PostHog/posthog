import { useActions, useValues, BindLogic } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { IconTuning, SortableDragIcon } from 'lib/components/icons'
import { RestrictedArea, RestrictedComponentProps, RestrictionScope } from 'lib/components/RestrictedArea'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Tooltip } from 'lib/components/Tooltip'
import { CloseOutlined, LockOutlined } from '@ant-design/icons'
import {
    SortableContainer as sortableContainer,
    SortableElement as sortableElement,
    SortableHandle as sortableHandle,
} from 'react-sortable-hoc'
import VirtualizedList, { ListRowProps } from 'react-virtualized/dist/es/List'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import Modal from 'antd/lib/modal/Modal'
import { Button, Col, Row, Space } from 'antd'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TeamMembershipLevel } from 'lib/constants'
import { useState } from 'react'
import { columnConfiguratorLogic, ColumnConfiguratorLogicProps } from './columnConfiguratorLogic'
import { defaultDataTableStringColumns } from '../defaults'
import { DataTableNode } from '~/queries/schema'

let uniqueNode = 0

interface ColumnConfiguratorProps {
    query: DataTableNode
    setQuery?: (node: DataTableNode) => void
}

export function ColumnConfigurator({ query, setQuery }: ColumnConfiguratorProps): JSX.Element {
    const { columns } = useValues(dataTableLogic)

    const [key] = useState(() => String(uniqueNode++))
    const columnConfiguratorLogicProps: ColumnConfiguratorLogicProps = {
        key,
        columns,
        setColumns: (columns: string[]) => {
            setQuery?.({ ...query, columns })
        },
    }
    const { showModal } = useActions(columnConfiguratorLogic(columnConfiguratorLogicProps))

    return (
        <BindLogic logic={columnConfiguratorLogic} props={columnConfiguratorLogicProps}>
            <LemonButton
                type="secondary"
                data-attr="events-table-column-selector"
                icon={<IconTuning style={{ color: 'var(--primary)' }} />}
                onClick={showModal}
            >
                Configure columns
            </LemonButton>
            <ColumnConfiguratorModal />
        </BindLogic>
    )
}

function ColumnConfiguratorModal(): JSX.Element {
    // the virtualised list doesn't support gaps between items in the list
    // setting the container to be larger than we need
    // and adding a container with a smaller height to each row item
    // allows the new row item to set a margin around itself
    const rowContainerHeight = 36
    const rowItemHeight = 32

    const { modalVisible, columns } = useValues(columnConfiguratorLogic)
    const { hideModal, setColumns, resetColumns, selectColumn, unselectColumn, save, toggleSaveAsDefault } =
        useActions(columnConfiguratorLogic)

    const immutableColumns: string[] = []

    function SaveColumnsAsDefault({ isRestricted }: RestrictedComponentProps): JSX.Element {
        return (
            <LemonCheckbox
                label="Save as default for all project members"
                className="mt-2"
                data-attr="events-table-save-columns-as-default-toggle"
                bordered
                onChange={toggleSaveAsDefault}
                defaultChecked={false}
                disabled={isRestricted}
            />
        )
    }
    const DragHandle = sortableHandle(() => (
        <span className="drag-handle">
            <SortableDragIcon />
        </span>
    ))
    const SelectedColumn = ({ column, disabled }: { column: string; disabled?: boolean }): JSX.Element => {
        return (
            <div
                className={clsx(['column-display-item', { selected: !disabled, disabled: disabled }])}
                style={{ height: `${rowItemHeight}px` }}
            >
                {!disabled && <DragHandle />}
                <PropertyKeyInfo
                    value={
                        column.startsWith('properties.')
                            ? column.substring(11)
                            : column.startsWith('person.properties')
                            ? column.substring(18)
                            : column
                    }
                />
                <div className="text-right" style={{ flex: 1 }}>
                    <Tooltip title={disabled ? 'Reserved' : 'Remove'}>
                        {disabled ? (
                            <LockOutlined />
                        ) : (
                            <CloseOutlined
                                data-attr="column-display-item-remove-icon"
                                style={{ color: 'var(--danger)' }}
                                onClick={() => unselectColumn(column)}
                            />
                        )}
                    </Tooltip>
                </div>
            </div>
        )
    }

    const SortableSelectedColumn = sortableElement(SelectedColumn)

    const SortableSelectedColumnRenderer = ({ index, style, key }: ListRowProps): JSX.Element => {
        const disabled = immutableColumns?.includes(columns[index])
        return (
            <div style={style} key={key}>
                {disabled && <SelectedColumn column={columns[index]} disabled={Boolean(disabled)} />}
                {!disabled && (
                    <SortableSelectedColumn column={columns[index]} index={index} collection="selected-columns" />
                )}
            </div>
        )
    }

    const SortableColumnList = sortableContainer(() => (
        <div style={{ height: 320 }} className="selected-columns-col">
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => {
                    return (
                        <VirtualizedList
                            height={height}
                            rowCount={columns.length}
                            rowRenderer={SortableSelectedColumnRenderer}
                            rowHeight={rowContainerHeight}
                            width={width}
                        />
                    )
                }}
            </AutoSizer>
        </div>
    ))

    const handleSort = ({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void => {
        const newColumns = [...columns]
        const [removed] = newColumns.splice(oldIndex, 1)
        newColumns.splice(newIndex, 0, removed)
        setColumns(newColumns)
    }

    return (
        <Modal
            id="column-configurator-modal"
            centered
            visible={modalVisible}
            title="Configure columns"
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
                        <Button className="text-blue" onClick={() => resetColumns(defaultDataTableStringColumns)}>
                            Reset to defaults
                        </Button>
                    </Space>
                    <Space>
                        <Button className="text-blue" type="text" onClick={hideModal}>
                            Close
                        </Button>
                        <Button type="primary" onClick={save}>
                            Save
                        </Button>
                    </Space>
                </Row>
            }
        >
            <div className="main-content">
                <Row gutter={16} className="lists">
                    <Col xs={24} sm={12}>
                        <h4 className="secondary uppercase text-muted">
                            Visible columns ({columns.length}) - Drag to reorder
                        </h4>
                        <SortableColumnList
                            helperClass="column-configurator-modal-sortable-container"
                            onSortEnd={handleSort}
                            distance={5}
                            useDragHandle
                            lockAxis="y"
                        />
                    </Col>
                    <Col xs={24} sm={12}>
                        <h4 className="secondary uppercase text-muted">Available columns</h4>
                        <div style={{ height: 320 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => {
                                    return (
                                        <TaxonomicFilter
                                            height={height}
                                            width={width}
                                            taxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.EventProperties,
                                                TaxonomicFilterGroupType.EventFeatureFlags,
                                            ]}
                                            value={undefined}
                                            onChange={(_, value) => value && selectColumn(`properties.${value}`)}
                                            popoverEnabled={false}
                                            selectFirstItem={false}
                                            excludedProperties={{
                                                [TaxonomicFilterGroupType.EventProperties]: columns,
                                                [TaxonomicFilterGroupType.EventFeatureFlags]: columns,
                                            }}
                                        />
                                    )
                                }}
                            </AutoSizer>
                        </div>
                    </Col>
                </Row>
                <RestrictedArea
                    Component={SaveColumnsAsDefault}
                    minimumAccessLevel={TeamMembershipLevel.Admin}
                    scope={RestrictionScope.Project}
                />
            </div>
        </Modal>
    )
}
