import { useActions } from 'kea'

import { IconCalendar, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { BIField } from '~/queries/schema/schema-business-intelligence'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import {
    BI_FIELD_DRAG_MIME_TYPE,
    getBIDropTarget,
    serializeBIField,
    isNumericBIField,
} from 'products/business_intelligence/frontend/biEditorTypes'

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

export function BIDataPaneField({
    field,
    measure,
    path = [],
}: {
    field: BIField
    measure: boolean
    path?: string[]
}): JSX.Element {
    const { addFieldToShelf, editLocalField } = useActions(biEditorLogic)
    const addField = (field: BIField): void => {
        const target = getBIDropTarget(field, 'rows')
        addFieldToShelf(target.field, target.shelf)
    }
    return (
        <div className="flex min-w-0 items-center group/bi-field">
            <button
                key={field.id}
                type="button"
                draggable
                title={field.name}
                className={cn(
                    'flex h-6 w-full min-w-0 cursor-grab items-center gap-1 rounded px-1 text-left text-xs hover:bg-fill-highlight-100',
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
            {(field.localDefinition || isNumericBIField(field) || ['string', 'boolean'].includes(field.type)) && (
                <LemonMenu
                    items={
                        field.localDefinition
                            ? [
                                  {
                                      label: 'Edit local definition',
                                      onClick: () => editLocalField(field, field.localDefinition!.kind),
                                  },
                              ]
                            : [
                                  { label: 'Group categories', onClick: () => editLocalField(field, 'groups') },
                                  ...(isNumericBIField(field)
                                      ? [{ label: 'Create numeric bins', onClick: () => editLocalField(field, 'bins') }]
                                      : []),
                              ]
                    }
                >
                    <LemonButton
                        size="xxsmall"
                        icon={<IconEllipsis />}
                        aria-label={`Options for ${field.name}`}
                        className="shrink-0 opacity-0 group-hover/bi-field:opacity-100 focus:opacity-100"
                    />
                </LemonMenu>
            )}
        </div>
    )
}
