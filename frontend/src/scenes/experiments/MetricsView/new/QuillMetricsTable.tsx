import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { type ReactNode } from 'react'

import { IconDrag } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { verticalSortableListCollisionDetection } from 'lib/sortable'

import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'

import { QuillMetricCard } from './QuillMetricCard'
import { metricName, useMetricsTableModel } from './useMetricsTableModel'

function SortableMetricCard({
    uuid,
    name,
    disabled,
    children,
}: {
    uuid: string
    name: string
    disabled: boolean
    children: (dragHandle: JSX.Element | null) => ReactNode
}): JSX.Element {
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id: uuid,
        disabled,
    })

    return (
        <div
            ref={disabled ? undefined : setNodeRef}
            className="relative"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Transform.toString(transform),
                transition: isDragging ? 'none' : transition,
                zIndex: isDragging ? 2 : undefined,
            }}
        >
            {children(
                disabled ? null : (
                    <Button
                        ref={setActivatorNodeRef}
                        size="icon-xs"
                        className="-ml-1 shrink-0 cursor-grab touch-none active:cursor-grabbing"
                        aria-label={`Reorder ${name}`}
                        tooltip="Drag to reorder metrics"
                        {...listeners}
                        {...attributes}
                        data-attr="experiment-metric-drag-handle"
                    >
                        <IconDrag />
                    </Button>
                )
            )}
        </div>
    )
}

export function QuillMetricsTable({
    metrics,
    results,
    errors,
    isSecondary,
    showDetailsModal = true,
    footer,
}: {
    metrics: ExperimentMetric[]
    results: (NewExperimentQueryResponse | undefined)[]
    errors: any[]
    isSecondary: boolean
    showDetailsModal?: boolean
    footer?: ReactNode
}): JSX.Element {
    const {
        experiment,
        exposuresLoading,
        axisRange,
        statsMethod,
        sequentialTestingEnabled,
        sensors,
        orderedUuids,
        dragDisabled,
        handleDragEnd,
        announcements,
        handlersFor,
    } = useMetricsTableModel({ metrics, results, errors, isSecondary })

    return (
        <DndContext
            sensors={sensors}
            collisionDetection={verticalSortableListCollisionDetection}
            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
            autoScroll={{ canScroll: (element) => element === document.scrollingElement }}
            accessibility={{ announcements }}
            onDragEnd={handleDragEnd}
        >
            <SortableContext items={orderedUuids} strategy={verticalListSortingStrategy}>
                <div className="flex flex-col gap-3" data-attr="experiment-metrics-cards">
                    {metrics.map((metric, index) => {
                        const result = results[index] ?? null
                        const error = errors[index]
                        return (
                            <SortableMetricCard
                                key={metric.uuid || index}
                                uuid={metric.uuid || String(index)}
                                name={metricName(metric)}
                                disabled={dragDisabled}
                            >
                                {(dragHandle) => (
                                    <QuillMetricCard
                                        metric={metric}
                                        result={result}
                                        error={error}
                                        experiment={experiment}
                                        axisRange={axisRange}
                                        isSecondary={isSecondary}
                                        statsMethod={statsMethod}
                                        sequentialTestingEnabled={sequentialTestingEnabled}
                                        dragHandle={dragHandle}
                                        isLoading={!result && !error && isLaunched(experiment)}
                                        exposuresLoading={exposuresLoading}
                                        showDetailsModal={showDetailsModal}
                                        footer={index === 0 ? footer : undefined}
                                        {...handlersFor(metric)}
                                    />
                                )}
                            </SortableMetricCard>
                        )
                    })}
                </div>
            </SortableContext>
        </DndContext>
    )
}
