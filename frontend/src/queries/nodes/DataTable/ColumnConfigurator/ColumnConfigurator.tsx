import './ColumnConfigurator.scss'
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
import { Col, Row } from 'antd'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TeamMembershipLevel } from 'lib/constants'
import { useState } from 'react'
import { columnConfiguratorLogic, ColumnConfiguratorLogicProps } from './columnConfiguratorLogic'
import { defaultDataTableStringColumns } from '../defaults'
import { DataTableNode } from '~/queries/schema'
import { LemonModal } from 'lib/components/LemonModal'

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
    const { hideModal, setColumns, selectColumn, unselectColumn, save, toggleSaveAsDefault } =
        useActions(columnConfiguratorLogic)

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
                <div className="text-right flex-1">
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
        return (
            <div style={style} key={key}>
                <SortableSelectedColumn column={columns[index]} index={index} collection="selected-columns" />
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
        <LemonModal
            isOpen={modalVisible}
            title="Configure columns"
            onClose={hideModal}
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton type="secondary" onClick={() => setColumns(defaultDataTableStringColumns)}>
                            Reset to defaults
                        </LemonButton>
                    </div>
                    <LemonButton type="secondary" onClick={hideModal}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" onClick={save} data-attr="items-selector-confirm">
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="ColumnConfiguratorModal main-content">
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
                                    const trimmedProperties = columns.map((c) =>
                                        c.replace('person.', '').replace('properties.', '')
                                    )
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
                                                [TaxonomicFilterGroupType.EventProperties]: trimmedProperties,
                                                [TaxonomicFilterGroupType.EventFeatureFlags]: trimmedProperties,
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
        </LemonModal>
    )
}
