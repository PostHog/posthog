import './ColumnConfigurator.scss'
import { BindLogic, useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { IconClose, IconEdit, IconTuning, SortableDragIcon } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'
import { columnConfiguratorLogic, ColumnConfiguratorLogicProps } from './columnConfiguratorLogic'
import { defaultDataTableColumns, extractExpressionComment, removeExpressionComment } from '../utils'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { isEventsQuery, taxonomicEventFilterToHogQL, trimQuotes } from '~/queries/utils'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { PropertyFilterType } from '~/types'
import { TeamMembershipLevel } from 'lib/constants'
import { RestrictedArea, RestrictedComponentProps, RestrictionScope } from 'lib/components/RestrictedArea'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { DndContext } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'

let uniqueNode = 0

interface ColumnConfiguratorProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
}

export function ColumnConfigurator({ query, setQuery }: ColumnConfiguratorProps): JSX.Element {
    const { columnsInQuery } = useValues(dataTableLogic)

    const [key] = useState(() => String(uniqueNode++))
    const columnConfiguratorLogicProps: ColumnConfiguratorLogicProps = {
        key,
        isPersistent: !!query.showPersistentColumnConfigurator,
        columns: columnsInQuery,
        setColumns: (columns: string[]) => {
            if (isEventsQuery(query.source)) {
                let orderBy = query.source.orderBy
                if (orderBy && orderBy.length > 0) {
                    const orderColumn = removeExpressionComment(
                        orderBy[0].endsWith(' DESC') ? orderBy[0].replace(/ DESC$/, '') : orderBy[0]
                    )
                    // the old orderBy column was removed, so remove it from the new query
                    if (!columns.some((c) => removeExpressionComment(c) === orderColumn)) {
                        orderBy = undefined
                    }
                }
                setQuery?.({
                    ...query,
                    source: {
                        ...query.source,
                        orderBy,
                        select: columns,
                    },
                })
            } else {
                setQuery?.({ ...query, columns })
            }
        },
    }
    const { showModal } = useActions(columnConfiguratorLogic(columnConfiguratorLogicProps))

    return (
        <BindLogic logic={columnConfiguratorLogic} props={columnConfiguratorLogicProps}>
            <LemonButton
                type="secondary"
                data-attr="events-table-column-selector"
                icon={<IconTuning />}
                onClick={showModal}
            >
                Configure columns
            </LemonButton>
            <ColumnConfiguratorModal query={query} setQuery={setQuery} />
        </BindLogic>
    )
}

function ColumnConfiguratorModal({ query }: ColumnConfiguratorProps): JSX.Element {
    const { modalVisible, columns, saveAsDefault } = useValues(columnConfiguratorLogic)
    const { hideModal, moveColumn, setColumns, selectColumn, unselectColumn, save, toggleSaveAsDefault } =
        useActions(columnConfiguratorLogic)

    const onEditColumn = (column: string, index: number): void => {
        const newColumn = window.prompt('Edit column', column)
        if (newColumn) {
            setColumns(columns.map((c, i) => (i === index ? newColumn : c)))
        }
    }

    return (
        <LemonModal
            isOpen={modalVisible}
            title="Configure columns"
            onClose={hideModal}
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton
                            type="secondary"
                            onClick={() => setColumns(defaultDataTableColumns(NodeKind.EventsQuery))}
                        >
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
            <div className="ColumnConfiguratorModal">
                <div className="Columns">
                    <div className="HalfColumn">
                        <h4 className="secondary uppercase text-muted">
                            Visible columns ({columns.length}) - Drag to reorder
                        </h4>
                        <DndContext
                            onDragEnd={({ active, over }) => {
                                if (over && active.id !== over.id) {
                                    moveColumn(
                                        columns.indexOf(active.id.toString()),
                                        columns.indexOf(over.id.toString())
                                    )
                                }
                            }}
                            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                        >
                            <SortableContext items={columns} strategy={verticalListSortingStrategy}>
                                {columns.map((column, index) => (
                                    <SelectedColumn
                                        key={column}
                                        column={column}
                                        dataIndex={index}
                                        onEdit={onEditColumn}
                                        onRemove={unselectColumn}
                                    />
                                ))}
                            </SortableContext>
                        </DndContext>
                    </div>
                    <div className="HalfColumn">
                        <h4 className="secondary uppercase text-muted">Available columns</h4>
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div style={{ height: 360 }}>
                            <AutoSizer>
                                {({ height, width }: { height: number; width: number }) => (
                                    <TaxonomicFilter
                                        height={height}
                                        width={width}
                                        taxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.EventProperties,
                                            TaxonomicFilterGroupType.EventFeatureFlags,
                                            TaxonomicFilterGroupType.PersonProperties,
                                            ...(isEventsQuery(query.source)
                                                ? [TaxonomicFilterGroupType.HogQLExpression]
                                                : []),
                                        ]}
                                        value={undefined}
                                        onChange={(group, value) => {
                                            const column = taxonomicEventFilterToHogQL(group.type, value)
                                            if (column !== null) {
                                                selectColumn(column)
                                            }
                                        }}
                                        popoverEnabled={false}
                                        selectFirstItem={false}
                                    />
                                )}
                            </AutoSizer>
                        </div>
                    </div>
                </div>
                {isEventsQuery(query.source) && query.showPersistentColumnConfigurator ? (
                    <RestrictedArea
                        Component={function SaveColumnsAsDefault({
                            isRestricted,
                        }: RestrictedComponentProps): JSX.Element {
                            return (
                                <LemonCheckbox
                                    label="Save as default for all project members"
                                    className="mt-2"
                                    data-attr="events-table-save-columns-as-default-toggle"
                                    bordered
                                    checked={saveAsDefault}
                                    onChange={toggleSaveAsDefault}
                                    disabled={isRestricted}
                                />
                            )
                        }}
                        minimumAccessLevel={TeamMembershipLevel.Admin}
                        scope={RestrictionScope.Project}
                    />
                ) : null}
            </div>
        </LemonModal>
    )
}

const SelectedColumn = ({
    column,
    dataIndex,
    onEdit,
    onRemove,
}: {
    column: string
    dataIndex: number
    onEdit: (column: string, index: number) => void
    onRemove: (column: string) => void
}): JSX.Element => {
    const { setNodeRef, attributes, transform, transition, listeners } = useSortable({ id: column })

    let columnType: PropertyFilterType | null = null
    let columnKey = column
    if (column.startsWith('person.properties.')) {
        columnType = PropertyFilterType.Person
        columnKey = column.substring(18)
    }
    if (column.startsWith('properties.')) {
        columnType = PropertyFilterType.Event
        columnKey = column.substring(11)
    }

    columnKey = trimQuotes(extractExpressionComment(columnKey))

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
            }}
            {...attributes}
        >
            <div className="SelectedColumn">
                <span {...listeners} className="drag-handle">
                    <SortableDragIcon />
                </span>
                {columnType && <PropertyFilterIcon type={columnType} />}
                <PropertyKeyInfo className="ml-1" value={columnKey} />
                <div className="flex-1" />
                <Tooltip title="Edit">
                    <LemonButton onClick={() => onEdit(column, dataIndex)} status="primary" size="small">
                        <IconEdit data-attr="column-display-item-edit-icon" />
                    </LemonButton>
                </Tooltip>
                <Tooltip title="Remove">
                    <LemonButton onClick={() => onRemove(column)} status="danger" size="small">
                        <IconClose data-attr="column-display-item-remove-icon" />
                    </LemonButton>
                </Tooltip>
            </div>
        </div>
    )
}
