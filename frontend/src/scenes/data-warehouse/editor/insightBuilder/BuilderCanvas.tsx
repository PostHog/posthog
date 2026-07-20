import { DndContext, DragOverlay, PointerSensor, pointerWithin, useSensor, useSensors } from '@dnd-kit/core'
import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { BuilderWell, canDropInWell } from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'
import { InsightBuilderDimension, InsightBuilderMeasure } from '~/queries/schema/schema-general'

import { measureLabel } from './builderLabels'
import { BuilderPreview } from './BuilderPreview'
import { ChartTypePicker } from './ChartTypePicker'
import { FieldsPanel } from './FieldsPanel'
import {
    BuilderField,
    COUNT_STAR_COLUMN,
    DEFAULT_DATE_GRAIN,
    defaultAggregationForField,
    insightBuilderLogic,
} from './insightBuilderLogic'
import { Wells, parsePillId } from './Wells'

type DragData =
    | { type: 'field'; field: BuilderField }
    | { type: 'pill'; well: BuilderWell; index: number; item: InsightBuilderDimension | InsightBuilderMeasure }

function dragLabel(data: DragData): string {
    if (data.type === 'field') {
        return data.field.name === COUNT_STAR_COLUMN ? 'Count of rows' : data.field.name
    }
    return data.well === 'values' ? measureLabel(data.item as InsightBuilderMeasure) : data.item.column
}

export function BuilderCanvas({ tabId }: { tabId: string }): JSX.Element {
    const logic = insightBuilderLogic({ tabId })
    const { wells, builderDisplay, baseFields } = useValues(logic)
    const { addField, removeField, moveField } = useActions(logic)
    const [activeDragLabel, setActiveDragLabel] = useState<string | null>(null)

    // The 4px activation distance keeps plain clicks (menus, close buttons) from starting a drag
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

    const resolveTargetWell = (overId: string | number | undefined): BuilderWell | null => {
        if (typeof overId !== 'string') {
            return null
        }
        if (overId.startsWith('well:')) {
            return overId.slice('well:'.length) as BuilderWell
        }
        return parsePillId(overId)?.well ?? null
    }

    const addToWell = (
        targetWell: BuilderWell,
        column: string,
        source: Partial<BuilderField>,
        options?: {
            replace?: boolean
            dateGrain?: InsightBuilderDimension['dateGrain']
            aggregation?: InsightBuilderMeasure['aggregation']
        }
    ): void => {
        if (column === COUNT_STAR_COLUMN && targetWell !== 'values') {
            lemonToast.info('Count of rows can only go in Values')
            return
        }
        if (targetWell === 'values') {
            addField('values', column, {
                aggregation:
                    options?.aggregation ??
                    (column === COUNT_STAR_COLUMN
                        ? 'count'
                        : defaultAggregationForField({ isNumerical: source.isNumerical ?? true })),
                replace: options?.replace,
            })
        } else {
            addField(targetWell, column, {
                dateGrain: options?.dateGrain ?? (source.isDate ? DEFAULT_DATE_GRAIN : undefined),
                replace: options?.replace,
            })
        }
    }

    const onDragStart = (event: DragStartEvent): void => {
        const data = event.active.data.current as DragData | undefined
        setActiveDragLabel(data ? dragLabel(data) : null)
    }

    const onDragEnd = (event: DragEndEvent): void => {
        setActiveDragLabel(null)
        const { active, over } = event
        const targetWell = resolveTargetWell(over?.id)
        const data = active.data.current as DragData | undefined
        if (!targetWell || !data) {
            return
        }

        if (data.type === 'field') {
            const drop = canDropInWell(targetWell, wells, builderDisplay)
            if (drop.mode === 'deny') {
                if (drop.reason) {
                    lemonToast.info(drop.reason)
                }
                return
            }
            addToWell(targetWell, data.field.name, data.field, { replace: drop.mode === 'replace' })
            return
        }

        // Pill drag: reorder within a well, or transfer between wells
        if (data.well === targetWell) {
            const overPill = typeof over?.id === 'string' ? parsePillId(over.id) : null
            const toIndex = overPill ? overPill.index : wells[targetWell].length - 1
            moveField(targetWell, data.index, toIndex)
            return
        }

        const drop = canDropInWell(targetWell, wells, builderDisplay)
        if (drop.mode === 'deny') {
            if (drop.reason) {
                lemonToast.info(drop.reason)
            }
            return
        }
        const column = data.item.column
        const field = baseFields.find((candidate) => candidate.name === column)
        removeField(data.well, data.index)
        addToWell(targetWell, column, field ?? {}, {
            replace: drop.mode === 'replace',
            dateGrain: 'dateGrain' in data.item ? data.item.dateGrain : undefined,
            aggregation: 'aggregation' in data.item ? data.item.aggregation : undefined,
        })
    }

    return (
        <DndContext
            sensors={sensors}
            collisionDetection={pointerWithin}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDragCancel={() => setActiveDragLabel(null)}
        >
            <div className="flex min-h-0 flex-1 border-t" data-attr="sql-builder-canvas">
                <FieldsPanel tabId={tabId} />
                <div className="flex w-64 shrink-0 flex-col gap-4 overflow-y-auto border-r bg-surface-primary p-3">
                    <ChartTypePicker tabId={tabId} />
                    <Wells tabId={tabId} />
                </div>
                <BuilderPreview tabId={tabId} />
            </div>
            <DragOverlay dropAnimation={null}>
                {activeDragLabel ? (
                    <span className="inline-flex items-center rounded bg-accent-highlight-secondary px-2 py-1 text-sm shadow-md">
                        {activeDragLabel}
                    </span>
                ) : null}
            </DragOverlay>
        </DndContext>
    )
}
