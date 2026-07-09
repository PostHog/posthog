import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconDrag } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { ExperimentMetric } from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { MetricTitle } from './shared/MetricTitle'
import { getMetricTag } from './shared/utils'

const MetricItem = ({
    metric,
    order,
    isRemoved,
    isMoved,
    canLeave,
    moveTargetLabel,
    onRemove,
    onMove,
    onRestore,
}: {
    metric: ExperimentMetric & { sharedMetricId?: number; isSharedMetric?: boolean }
    order: number
    isRemoved: boolean
    isMoved: boolean
    canLeave: boolean
    moveTargetLabel: string
    onRemove: () => void
    onMove: () => void
    onRestore: () => void
}): JSX.Element => {
    const uuid = metric.uuid || (metric as any).query?.uuid
    const isStaged = isRemoved || isMoved
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: uuid,
        disabled: isStaged,
    })

    return (
        <div
            ref={setNodeRef}
            className={clsx(
                'relative flex items-center gap-2 p-3 border rounded bg-bg-light',
                isDragging && 'z-[999999]'
            )}
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
            }}
            {...attributes}
        >
            <div
                className={clsx('flex-shrink-0', isStaged ? 'cursor-default' : 'cursor-move')}
                {...(isStaged ? {} : listeners)}
            >
                <IconDrag className={clsx('text-lg', isStaged ? 'text-muted' : 'text-orange-500')} />
            </div>
            <LemonBadge.Number count={order + 1} maxDigits={3} status="muted" />
            <div
                className={clsx(
                    'flex-1 min-w-0 flex flex-col gap-1',
                    isRemoved && 'line-through opacity-50',
                    isMoved && 'opacity-50'
                )}
            >
                <div className="font-semibold">
                    <MetricTitle metric={metric} />
                </div>
                <div className="flex gap-1">
                    <LemonTag type="muted" size="small">
                        {getMetricTag(metric)}
                    </LemonTag>
                    {metric.isSharedMetric && (
                        <LemonTag type="option" size="small">
                            Shared
                        </LemonTag>
                    )}
                </div>
            </div>
            {isStaged ? (
                <>
                    {isMoved && (
                        <LemonTag type="highlight" size="small">
                            Moving to {moveTargetLabel}
                        </LemonTag>
                    )}
                    <LemonButton size="small" type="secondary" onClick={onRestore}>
                        Restore
                    </LemonButton>
                </>
            ) : (
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={onMove}
                        disabledReason={!canLeave ? 'At least one metric is required' : undefined}
                    >
                        Move to {moveTargetLabel}
                    </LemonButton>
                    <LemonButton
                        size="small"
                        status="danger"
                        type="secondary"
                        onClick={onRemove}
                        disabledReason={!canLeave ? 'At least one metric is required' : undefined}
                    >
                        Remove
                    </LemonButton>
                </>
            )}
        </div>
    )
}

export function MetricsReorderModal({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { isPrimaryMetricsReorderModalOpen, isSecondaryMetricsReorderModalOpen } = useValues(modalsLogic)
    const { closePrimaryMetricsReorderModal, closeSecondaryMetricsReorderModal } = useActions(modalsLogic)

    const isOpen = isSecondary ? isSecondaryMetricsReorderModalOpen : isPrimaryMetricsReorderModalOpen
    const closeModal = isSecondary ? closeSecondaryMetricsReorderModal : closePrimaryMetricsReorderModal

    const { experiment, getOrderedMetricsWithResults, experimentUpdateLoading } = useValues(experimentLogic)
    const { saveMetricsReorder } = useActions(experimentLogic)

    const moveTargetLabel = isSecondary ? 'primary' : 'secondary'

    const [orderedUuids, setOrderedUuids] = useState<string[]>([])
    const [removedUuids, setRemovedUuids] = useState<Set<string>>(new Set())
    const [movedUuids, setMovedUuids] = useState<Set<string>>(new Set())

    useEffect(() => {
        if (isOpen && experiment) {
            const currentOrder = isSecondary
                ? (experiment.secondary_metrics_ordered_uuids ?? [])
                : (experiment.primary_metrics_ordered_uuids ?? [])
            setOrderedUuids([...currentOrder])
        } else {
            setOrderedUuids([])
        }
        setRemovedUuids(new Set())
        setMovedUuids(new Set())
    }, [
        isOpen,
        isSecondary,
        experiment.primary_metrics_ordered_uuids,
        experiment.secondary_metrics_ordered_uuids,
        experiment,
    ])

    const displayMetrics = (() => {
        if (!experiment || orderedUuids.length === 0) {
            return []
        }

        const metricsWithResults = getOrderedMetricsWithResults(isSecondary)
        const allMetrics = metricsWithResults.map(({ metric }: { metric: any }) => metric)

        const metricsMap = new Map()
        allMetrics.forEach((metric: any) => {
            const uuid = metric.uuid || metric.query?.uuid
            if (uuid) {
                metricsMap.set(uuid, metric)
            }
        })

        return orderedUuids.map((uuid) => metricsMap.get(uuid)).filter(Boolean)
    })()

    // Moved metrics leave the section just like removed ones, so both count
    // against the at-least-one-primary-metric requirement.
    const activeCount = orderedUuids.length - removedUuids.size - movedUuids.size
    const canLeaveMore = isSecondary || activeCount > 1

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (active.id && over && active.id !== over.id) {
            const from = orderedUuids.indexOf(active.id as string)
            const to = orderedUuids.indexOf(over.id as string)

            if (from !== -1 && to !== -1) {
                const newOrder = arrayMove(orderedUuids, from, to)
                setOrderedUuids(newOrder)
            }
        }
    }

    const handleSave = (): void => {
        // The listener persists everything in one update, realigns results, and
        // closes the modal on completion.
        saveMetricsReorder(isSecondary, orderedUuids, Array.from(removedUuids), Array.from(movedUuids))
    }

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            width={600}
            title={`Reorder ${isSecondary ? 'secondary' : 'primary'} metrics`}
            description={
                <p>
                    Drag and drop to reorder, move metrics to the {moveTargetLabel} section, or remove metrics you no
                    longer need.
                </p>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave} loading={experimentUpdateLoading}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <DndContext modifiers={[restrictToVerticalAxis, restrictToParentElement]} onDragEnd={handleDragEnd}>
                    <SortableContext items={orderedUuids} strategy={verticalListSortingStrategy}>
                        {isOpen && displayMetrics.length === 0 && (
                            <div className="p-4 text-center text-muted">
                                <p>No metrics available for reordering</p>
                            </div>
                        )}
                        {displayMetrics.map((metric, index) => {
                            const uuid = metric.uuid || (metric as any).query?.uuid
                            const isRemoved = removedUuids.has(uuid)
                            const isMoved = movedUuids.has(uuid)
                            const effectiveIndex =
                                displayMetrics.slice(0, index + 1).filter((m) => {
                                    const id = m.uuid || (m as any).query?.uuid
                                    return !removedUuids.has(id) && !movedUuids.has(id)
                                }).length - 1
                            return (
                                <MetricItem
                                    key={uuid}
                                    metric={metric}
                                    order={isRemoved || isMoved ? index : effectiveIndex}
                                    isRemoved={isRemoved}
                                    isMoved={isMoved}
                                    canLeave={canLeaveMore}
                                    moveTargetLabel={moveTargetLabel}
                                    onRemove={() => setRemovedUuids((prev) => new Set([...prev, uuid]))}
                                    onMove={() => setMovedUuids((prev) => new Set([...prev, uuid]))}
                                    onRestore={() => {
                                        setRemovedUuids((prev) => {
                                            const next = new Set(prev)
                                            next.delete(uuid)
                                            return next
                                        })
                                        setMovedUuids((prev) => {
                                            const next = new Set(prev)
                                            next.delete(uuid)
                                            return next
                                        })
                                    }}
                                />
                            )
                        })}
                    </SortableContext>
                </DndContext>
            </div>
        </LemonModal>
    )
}
