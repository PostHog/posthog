import { useActions } from 'kea'

import { IconCalendar } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'
import { biEditorLogic } from 'scenes/data-warehouse/editor/bi/biEditorLogic'
import {
    BIField,
    BI_FIELD_DRAG_MIME_TYPE,
    getBIDropTarget,
    serializeBIField,
} from 'scenes/data-warehouse/editor/bi/biEditorTypes'

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

export function BIDataPaneSection({
    title,
    fields,
    measure,
    emptyText,
    path = [],
}: {
    title?: string
    fields: BIField[]
    measure: boolean
    emptyText: string
    path?: string[]
}): JSX.Element {
    const { addFieldToShelf } = useActions(biEditorLogic)

    const addField = (field: BIField): void => {
        const target = getBIDropTarget(field, 'rows')
        addFieldToShelf(target.field, target.shelf)
    }

    return (
        <div className="flex flex-col">
            {title ? <div className="px-2 pb-1 pt-2 text-xs font-semibold text-secondary">{title}</div> : null}
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
                    onClick={(event) => {
                        if (event.detail === 0) {
                            addField(field)
                        }
                    }}
                    data-attr={measure ? 'bi-editor-data-pane-measure' : 'bi-editor-data-pane-dimension'}
                >
                    <FieldTypeGlyph field={field} measure={measure} />
                    <span className="truncate">
                        {path.length ? field.name.slice(path.join('.').length + 1) : field.name}
                    </span>
                </button>
            ))}
        </div>
    )
}
