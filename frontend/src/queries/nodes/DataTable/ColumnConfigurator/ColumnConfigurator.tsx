import './ColumnConfigurator.scss'

import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { IconPencil, IconX } from '@posthog/icons'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TeamMembershipLevel } from 'lib/constants'
import { IconTuning, SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'

import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { isEventsQuery, taxonomicEventFilterToHogQL, trimQuotes } from '~/queries/utils'
import { PropertyFilterType } from '~/types'

import { defaultDataTableColumns, extractExpressionComment, removeExpressionComment } from '../utils'
import { columnConfiguratorLogic, ColumnConfiguratorLogicProps } from './columnConfiguratorLogic'

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
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: TeamMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })
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
                    <LemonCheckbox
                        label="Save as default for all project members"
                        className="mt-2"
                        data-attr="events-table-save-columns-as-default-toggle"
                        bordered
                        checked={saveAsDefault}
                        onChange={toggleSaveAsDefault}
                        disabledReason={restrictionReason}
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
    let filterGroupType: TaxonomicFilterGroupType | undefined
    let columnKey = column
    if (column.startsWith('person.properties.')) {
        columnType = PropertyFilterType.Person
        filterGroupType = TaxonomicFilterGroupType.PersonProperties
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
                <PropertyKeyInfo
                    className="ml-1"
                    value={columnKey}
                    type={filterGroupType || TaxonomicFilterGroupType.EventProperties}
                />
                <div className="flex-1" />
                <Tooltip title="Edit">
                    <LemonButton onClick={() => onEdit(column, dataIndex)} size="small">
                        <IconPencil data-attr="column-display-item-edit-icon" />
                    </LemonButton>
                </Tooltip>
                <Tooltip title="Remove">
                    <LemonButton onClick={() => onRemove(column)} status="danger" size="small">
                        <IconX data-attr="column-display-item-remove-icon" />
                    </LemonButton>
                </Tooltip>
            </div>
        </div>
    )
}
