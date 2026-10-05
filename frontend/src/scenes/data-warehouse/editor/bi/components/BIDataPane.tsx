import { useActions, useValues } from 'kea'

import { IconCalendar, IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { BIDataSourcePicker } from 'products/data_warehouse/frontend/bi/BIDataSourcePicker'

import { editorSizingLogic } from '../../editorSizingLogic'
import { queryDatabaseLogic } from '../../sidebar/queryDatabaseLogic'
import { biEditorLogic } from '../biEditorLogic'
import { BIField, BI_FIELD_DRAG_MIME_TYPE, getBIDropTarget, serializeBIField } from '../biEditorTypes'

function FieldTypeGlyph({ field, measure }: { field: BIField; measure: boolean }): JSX.Element {
    const glyph =
        field.type === 'date' || field.type === 'datetime' ? (
            <IconCalendar />
        ) : measure || ['integer', 'float', 'decimal'].includes(field.type) ? (
            '#'
        ) : field.type === 'boolean' ? (
            'T|F'
        ) : field.type === 'json' || field.type === 'array' ? (
            '{ }'
        ) : (
            'Abc'
        )
    return (
        <span
            className={cn(
                'flex w-7 shrink-0 justify-center font-mono text-[10px] font-semibold',
                measure ? 'text-success' : 'text-brand-blue'
            )}
        >
            {glyph}
        </span>
    )
}

function DataPaneSection({
    title,
    fields,
    measure,
    emptyText,
}: {
    title: string
    fields: BIField[]
    measure: boolean
    emptyText: string
}): JSX.Element {
    const { addFieldToShelf } = useActions(biEditorLogic)

    const addField = (field: BIField): void => {
        const target = getBIDropTarget(field, 'rows')
        addFieldToShelf(target.field, target.shelf)
    }

    return (
        <div className="flex flex-col">
            <div className="px-2 pb-1 pt-2 text-xs font-semibold text-secondary">{title}</div>
            {fields.length === 0 ? <span className="px-2 text-xs text-tertiary">{emptyText}</span> : null}
            {fields.map((field) => (
                <button
                    key={field.id}
                    type="button"
                    draggable
                    title={field.name}
                    className={cn(
                        'flex h-6 w-full cursor-grab items-center gap-1 rounded px-1 text-left text-xs hover:bg-fill-highlight-100',
                        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent'
                    )}
                    onDragStart={(event) => {
                        event.dataTransfer.effectAllowed = 'copy'
                        event.dataTransfer.setData(BI_FIELD_DRAG_MIME_TYPE, serializeBIField(field))
                    }}
                    onDoubleClick={() => addField(field)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            addField(field)
                        }
                    }}
                    data-attr={measure ? 'bi-editor-data-pane-measure' : 'bi-editor-data-pane-dimension'}
                >
                    <FieldTypeGlyph field={field} measure={measure} />
                    <span className="truncate">{field.name}</span>
                </button>
            ))}
        </div>
    )
}

/** Lists the selected table's fields as dimensions and measures, ready to drag onto shelves. */
export function BIDataPane(): JSX.Element {
    const {
        config,
        dataPaneFields,
        dataPaneFieldsLoading,
        dataPaneFieldsError,
        dataPaneSearch,
        filteredDataPaneFields,
    } = useValues(biEditorLogic)
    const { editCalculatedMeasure, hydrateTableFields, setDataPaneSearch } = useActions(biEditorLogic)
    const { isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    const { locateTable } = useActions(queryDatabaseLogic)

    const hasFields = dataPaneFields.dimensions.length > 0 || dataPaneFields.measures.length > 0
    const hasMatches = filteredDataPaneFields.dimensions.length > 0 || filteredDataPaneFields.measures.length > 0

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex items-center justify-between gap-1 px-2 pt-2">
                <span className="text-sm font-semibold">Data</span>
                {!isDatabaseTreeCollapsed ? (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        disabledReason={!config.source ? 'Select a data source first' : undefined}
                        tooltip="Show this table in the database tree"
                        onClick={() => {
                            if (config.source) {
                                locateTable(config.source.table)
                            }
                        }}
                    >
                        Locate
                    </LemonButton>
                ) : null}
            </div>
            <div className="flex flex-col gap-1.5 p-2">
                <BIDataSourcePicker />
                {config.source ? (
                    <LemonInput
                        type="search"
                        size="small"
                        value={dataPaneSearch}
                        onChange={setDataPaneSearch}
                        placeholder="Search fields"
                        aria-label="Search fields"
                    />
                ) : null}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">
                {!config.source ? (
                    <p className="px-2 text-xs text-secondary">
                        Select a table to list its fields. You can also drag columns from the database tree.
                    </p>
                ) : dataPaneFieldsLoading && !hasFields ? (
                    <div className="flex items-center gap-2 px-2 text-xs text-secondary">
                        <Spinner /> Loading fields
                    </div>
                ) : dataPaneFieldsError ? (
                    <div className="flex flex-col items-start gap-2 px-2 text-xs text-secondary">
                        <span>Couldn't load fields for this table.</span>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            loading={dataPaneFieldsLoading}
                            onClick={() => config.source && hydrateTableFields([config.source.table])}
                        >
                            Retry
                        </LemonButton>
                    </div>
                ) : !hasFields ? (
                    <p className="px-2 text-xs text-secondary">
                        No fields found. Drag columns from the database tree instead.
                    </p>
                ) : !hasMatches ? (
                    <p className="px-2 text-xs text-secondary">No matching fields</p>
                ) : (
                    <>
                        <DataPaneSection
                            title="Dimensions"
                            fields={filteredDataPaneFields.dimensions}
                            measure={false}
                            emptyText="No matching dimensions"
                        />
                        <DataPaneSection
                            title="Measures"
                            fields={filteredDataPaneFields.measures}
                            measure
                            emptyText={
                                dataPaneSearch
                                    ? 'No matching measures'
                                    : 'No measures listed. Add a dimension to Rows, then choose Convert to measure from its menu.'
                            }
                        />
                    </>
                )}
            </div>
            <div className="border-t p-2">
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    fullWidth
                    type="secondary"
                    onClick={() => editCalculatedMeasure()}
                    disabledReason={!config.source ? 'Select a data source first' : undefined}
                    data-attr="bi-editor-add-calculated-measure"
                >
                    Add calculated measure
                </LemonButton>
            </div>
        </div>
    )
}
