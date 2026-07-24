import { useDraggable } from '@dnd-kit/core'
import { useActions, useValues } from 'kea'

import { IconCalendar, IconEllipsis } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { Icon123, IconTextSize } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { cn } from 'lib/utils/css-classes'

import {
    AGGREGATION_LABELS,
    DATE_GRAIN_LABELS,
    DATE_GRAIN_OPTIONS,
    NON_NUMERIC_AGGREGATIONS,
    NUMERIC_AGGREGATIONS,
} from '~/queries/nodes/DataVisualization/insightBuilder/builderLabels'
import { InsightBuilderAggregation } from '~/queries/schema/schema-general'

import { BuilderField, COUNT_STAR_COLUMN, DEFAULT_DATE_GRAIN, insightBuilderLogic } from './insightBuilderLogic'

export const COUNT_OF_ROWS_FIELD: BuilderField = {
    name: COUNT_STAR_COLUMN,
    typeName: 'INTEGER',
    isNumerical: true,
    isDate: false,
}

function FieldTypeIcon({ field }: { field: BuilderField }): JSX.Element {
    if (field.isDate) {
        return <IconCalendar className="text-tertiary shrink-0" />
    }
    if (field.isNumerical) {
        return <Icon123 className="text-tertiary shrink-0" />
    }
    return <IconTextSize className="text-tertiary shrink-0" />
}

function FieldRow({ tabId, field }: { tabId: string; field: BuilderField }): JSX.Element {
    const { addField } = useActions(insightBuilderLogic({ tabId }))
    const isCountOfRows = field.name === COUNT_STAR_COLUMN

    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `field:${field.name}`,
        data: { type: 'field', field },
    })

    const aggregations: InsightBuilderAggregation[] = field.isNumerical
        ? NUMERIC_AGGREGATIONS
        : NON_NUMERIC_AGGREGATIONS

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            className={cn(
                'group flex w-full cursor-grab items-center gap-2 rounded px-2 py-1 text-sm hover:bg-surface-secondary',
                isDragging && 'opacity-50'
            )}
            data-attr="sql-builder-field-row"
        >
            <FieldTypeIcon field={field} />
            <span className="min-w-0 flex-1 truncate">{isCountOfRows ? 'Count of rows' : field.name}</span>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <button
                            type="button"
                            // Revealed on row hover/focus so the row itself stays a clean drag handle
                            className="shrink-0 cursor-pointer rounded p-0.5 text-tertiary opacity-0 hover:bg-surface-primary hover:text-primary focus-visible:opacity-100 group-hover:opacity-100 data-[popup-open]:opacity-100"
                            aria-label={`Add ${isCountOfRows ? 'count of rows' : field.name} to the chart`}
                            // Bubble phase (not capture): let the trigger open first, then stop the
                            // event before the row's drag listeners see it
                            onPointerDown={(e) => e.stopPropagation()}
                            data-attr="sql-builder-field-menu"
                        />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                    {isCountOfRows ? (
                        <DropdownMenuItem
                            onClick={() => addField('values', COUNT_STAR_COLUMN, { aggregation: 'count' })}
                        >
                            Add to Values
                        </DropdownMenuItem>
                    ) : (
                        <>
                            {field.isDate ? (
                                <DropdownMenuSub>
                                    <DropdownMenuSubTrigger>Add to Rows</DropdownMenuSubTrigger>
                                    <DropdownMenuSubContent>
                                        {DATE_GRAIN_OPTIONS.map((grain) => (
                                            <DropdownMenuItem
                                                key={grain}
                                                onClick={() => addField('rows', field.name, { dateGrain: grain })}
                                            >
                                                By {DATE_GRAIN_LABELS[grain].toLowerCase()}
                                            </DropdownMenuItem>
                                        ))}
                                        <DropdownMenuItem onClick={() => addField('rows', field.name)}>
                                            Exact value
                                        </DropdownMenuItem>
                                    </DropdownMenuSubContent>
                                </DropdownMenuSub>
                            ) : (
                                <DropdownMenuItem onClick={() => addField('rows', field.name)}>
                                    Add to Rows
                                </DropdownMenuItem>
                            )}
                            <DropdownMenuItem
                                onClick={() =>
                                    addField(
                                        'columns',
                                        field.name,
                                        field.isDate ? { dateGrain: DEFAULT_DATE_GRAIN } : undefined
                                    )
                                }
                            >
                                Add to Columns
                            </DropdownMenuItem>
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger>Add to Values</DropdownMenuSubTrigger>
                                <DropdownMenuSubContent>
                                    {aggregations.map((aggregation) => (
                                        <DropdownMenuItem
                                            key={aggregation}
                                            onClick={() => addField('values', field.name, { aggregation })}
                                        >
                                            {AGGREGATION_LABELS[aggregation]}
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuItem onClick={() => addField('filters', field.name)}>
                                Add to Filters
                            </DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}

export function FieldsPanel({ tabId }: { tabId: string }): JSX.Element {
    const { baseFields, baseFieldsLoading, baseOutOfSync } = useValues(insightBuilderLogic({ tabId }))
    const { refreshBase } = useActions(insightBuilderLogic({ tabId }))

    const dimensions = baseFields.filter((field) => !field.isNumerical)
    const measures = baseFields.filter((field) => field.isNumerical)

    return (
        <div className="flex flex-col p-2">
            {baseOutOfSync ? (
                <LemonBanner
                    type="warning"
                    className="mb-2 text-xs"
                    action={{ children: 'Refresh fields', onClick: () => refreshBase() }}
                >
                    The base query changed.
                </LemonBanner>
            ) : null}
            {baseFieldsLoading ? (
                <div className="flex flex-col gap-2 p-2">
                    {Array.from({ length: 6 }, (_, index) => (
                        <LemonSkeleton key={index} className="h-5" />
                    ))}
                </div>
            ) : baseFields.length === 0 ? (
                <div className="flex flex-col gap-2 p-2 text-sm text-secondary">
                    <span>No fields yet. Run a query, then refresh.</span>
                    <LemonButton size="small" type="secondary" onClick={() => refreshBase()}>
                        Refresh fields
                    </LemonButton>
                </div>
            ) : (
                <>
                    <div className="px-2 pb-1 text-xs font-semibold uppercase text-tertiary">Dimensions</div>
                    {dimensions.length === 0 ? (
                        <div className="px-2 pb-2 text-xs text-secondary">No text or date columns</div>
                    ) : (
                        dimensions.map((field) => <FieldRow key={field.name} tabId={tabId} field={field} />)
                    )}
                    <div className="px-2 pb-1 pt-3 text-xs font-semibold uppercase text-tertiary">Measures</div>
                    <FieldRow tabId={tabId} field={COUNT_OF_ROWS_FIELD} />
                    {measures.map((field) => (
                        <FieldRow key={field.name} tabId={tabId} field={field} />
                    ))}
                </>
            )}
        </div>
    )
}
