import { useDraggable } from '@dnd-kit/core'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

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
    NON_NUMERIC_AGGREGATIONS,
    NUMERIC_AGGREGATIONS,
    dateGrainOptionsForField,
} from '~/queries/nodes/DataVisualization/insightBuilder/builderLabels'
import {
    addToWellDisabledReason,
    bestWellForField,
    wellLabel,
} from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'
import { InsightBuilderAggregation } from '~/queries/schema/schema-general'

import {
    BuilderField,
    COUNT_STAR_COLUMN,
    DEFAULT_DATE_GRAIN,
    defaultAggregationForField,
    insightBuilderLogic,
} from './insightBuilderLogic'

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
    const { builderDisplay, wells } = useValues(insightBuilderLogic({ tabId }))
    const isCountOfRows = field.name === COUNT_STAR_COLUMN
    const fieldLabel = isCountOfRows ? 'Count of rows' : field.name

    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `field:${field.name}`,
        data: { type: 'field', field },
    })
    const pointerDownPosition = useRef<{ x: number; y: number } | null>(null)

    const aggregations: InsightBuilderAggregation[] = field.isNumerical
        ? NUMERIC_AGGREGATIONS
        : NON_NUMERIC_AGGREGATIONS

    // Click-to-add mirrors the drag path's well/option mapping; the target well comes from the
    // current chart's capabilities so the field always lands somewhere visible
    const addFieldOnClick = (): void => {
        if (isCountOfRows) {
            addField('values', COUNT_STAR_COLUMN, { aggregation: 'count' })
            return
        }
        const well = bestWellForField(field, wells, builderDisplay)
        if (well === 'values') {
            addField('values', field.name, { aggregation: defaultAggregationForField(field) })
        } else {
            addField(well, field.name, field.isDate ? { dateGrain: DEFAULT_DATE_GRAIN } : undefined)
        }
    }

    // Dimension items speak the current chart's language ("Add to X-axis"), disabled with the
    // reason when the chart doesn't use the well; date fields get a grain submenu on whichever
    // dimension wells are enabled
    const renderDimensionItem = (well: 'rows' | 'columns'): JSX.Element => {
        const label = `Add to ${wellLabel(well, builderDisplay)}`
        const reason = addToWellDisabledReason(well, builderDisplay)
        if (reason) {
            return (
                <DropdownMenuItem disabled>
                    <span>{label}</span>
                    <span className="ml-auto pl-2 text-tertiary">{reason}</span>
                </DropdownMenuItem>
            )
        }
        if (field.isDate) {
            return (
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger>{label}</DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                        {dateGrainOptionsForField(field).map((grain) => (
                            <DropdownMenuItem
                                key={grain}
                                onClick={() => addField(well, field.name, { dateGrain: grain })}
                            >
                                By {DATE_GRAIN_LABELS[grain].toLowerCase()}
                            </DropdownMenuItem>
                        ))}
                        <DropdownMenuItem onClick={() => addField(well, field.name)}>Exact value</DropdownMenuItem>
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
            )
        }
        return <DropdownMenuItem onClick={() => addField(well, field.name)}>{label}</DropdownMenuItem>
    }

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
            <button
                type="button"
                className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left"
                onPointerDown={(e) => {
                    pointerDownPosition.current = { x: e.clientX, y: e.clientY }
                }}
                onClick={(e) => {
                    // A drag that ends back over the panel still fires a click — ignore anything
                    // that moved beyond the drag sensor's activation distance
                    const start = pointerDownPosition.current
                    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 4) {
                        return
                    }
                    addFieldOnClick()
                }}
                aria-label={`Add ${fieldLabel} to the chart`}
                data-attr="sql-builder-field-click-add"
            >
                <FieldTypeIcon field={field} />
                <span className="min-w-0 flex-1 truncate">{fieldLabel}</span>
            </button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <button
                            type="button"
                            // Revealed on row hover/focus so the row itself stays a clean drag handle
                            className="shrink-0 cursor-pointer rounded p-0.5 text-tertiary opacity-0 hover:bg-surface-primary hover:text-primary focus-visible:opacity-100 group-hover:opacity-100 data-[popup-open]:opacity-100"
                            aria-label={`Choose where to add ${fieldLabel}`}
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
                            Add to {wellLabel('values', builderDisplay)}
                        </DropdownMenuItem>
                    ) : (
                        <>
                            {renderDimensionItem('rows')}
                            {renderDimensionItem('columns')}
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger>
                                    Add to {wellLabel('values', builderDisplay)}
                                </DropdownMenuSubTrigger>
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
                    <span>No fields yet. Write a query in the Source tab, then refresh.</span>
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
