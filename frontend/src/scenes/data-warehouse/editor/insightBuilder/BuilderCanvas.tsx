import { DndContext, DragOverlay, PointerSensor, pointerWithin, useSensor, useSensors } from '@dnd-kit/core'
import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDatabase, IconGear, IconPalette } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { SideBar } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { measureLabel } from '~/queries/nodes/DataVisualization/insightBuilder/builderLabels'
import { BuilderWell, isWellEnabled } from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'
import { InsightBuilderDimension, InsightBuilderFilter, InsightBuilderMeasure } from '~/queries/schema/schema-general'

import { outputPaneLogic } from '../outputPaneLogic'
import { BuilderColumnShell } from './BuilderColumnShell'
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
    | {
          type: 'pill'
          well: BuilderWell
          index: number
          item: InsightBuilderDimension | InsightBuilderMeasure | InsightBuilderFilter
      }

function dragLabel(data: DragData): string {
    if (data.type === 'field') {
        return data.field.name === COUNT_STAR_COLUMN ? 'Count of rows' : data.field.name
    }
    return data.well === 'values' ? measureLabel(data.item as InsightBuilderMeasure) : data.item.column
}

export function BuilderCanvas({ tabId }: { tabId: string }): JSX.Element {
    const logic = insightBuilderLogic({ tabId })
    const { wells, filterItems, baseFields, builderDisplay, collapsedColumns } = useValues(logic)
    const { addField, removeField, moveField, toggleColumnCollapsed } = useActions(logic)
    const { fullscreen } = useValues(outputPaneLogic({ tabId }))
    const { setFullscreen } = useActions(outputPaneLogic({ tabId }))
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
            })
        } else if (targetWell === 'filters') {
            addField('filters', column)
        } else {
            addField(targetWell, column, {
                dateGrain: options?.dateGrain ?? (source.isDate ? DEFAULT_DATE_GRAIN : undefined),
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

        // Chart type is primary: reject drops onto a well the current chart doesn't use
        if (!isWellEnabled(targetWell, builderDisplay)) {
            lemonToast.info(`This chart type doesn't use ${targetWell}`)
            return
        }

        if (data.type === 'field') {
            addToWell(targetWell, data.field.name, data.field)
            return
        }

        // Pill drag: reorder within a well, or transfer between wells
        if (data.well === targetWell) {
            const overPill = typeof over?.id === 'string' ? parsePillId(over.id) : null
            const wellLength = targetWell === 'filters' ? filterItems.length : wells[targetWell].length
            const toIndex = overPill ? overPill.index : wellLength - 1
            moveField(targetWell, data.index, toIndex)
            return
        }

        const column = data.item.column
        const field = baseFields.find((candidate) => candidate.name === column)
        removeField(data.well, data.index)
        addToWell(targetWell, column, field ?? {}, {
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
            <div className="flex min-h-0 w-full flex-1 overflow-hidden" data-attr="sql-builder-canvas">
                <BuilderColumnShell
                    columnKey="data"
                    icon={<IconDatabase />}
                    label="Data"
                    side="left"
                    collapsed={!!collapsedColumns.data}
                    onToggle={() => toggleColumnCollapsed('data')}
                    headerExtra={
                        fullscreen ? (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() => setFullscreen(false)}
                                tooltip="Exit fullscreen to edit the SQL"
                                data-attr="sql-builder-edit-sql"
                            >
                                Edit SQL
                            </LemonButton>
                        ) : undefined
                    }
                >
                    <FieldsPanel tabId={tabId} />
                </BuilderColumnShell>
                <BuilderColumnShell
                    columnKey="setup"
                    icon={<IconGear />}
                    label="Setup"
                    side="left"
                    collapsed={!!collapsedColumns.setup}
                    onToggle={() => toggleColumnCollapsed('setup')}
                >
                    <div className="flex flex-col gap-4 p-3">
                        <ChartTypePicker tabId={tabId} />
                        <Wells tabId={tabId} />
                    </div>
                </BuilderColumnShell>
                {/* min-w-0 + overflow-hidden lets the chart absorb the squeeze so fixed side
                    columns (incl. Format) always stay on screen */}
                <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                    <BuilderPreview tabId={tabId} />
                </div>
                <BuilderColumnShell
                    columnKey="format"
                    icon={<IconPalette />}
                    label="Format"
                    side="right"
                    collapsed={!!collapsedColumns.format}
                    onToggle={() => toggleColumnCollapsed('format')}
                >
                    <SideBar className="w-full" />
                </BuilderColumnShell>
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
