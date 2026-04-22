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
    canRemove,
    onRemove,
    onRestore,
}: {
    metric: ExperimentMetric & { sharedMetricId?: number; isSharedMetric?: boolean }
    order: number
    isRemoved: boolean
    canRemove: boolean
    onRemove: () => void
    onRestore: () => void
}): JSX.Element => {
    const uuid = metric.uuid || (metric as any).query?.uuid
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: uuid,
        disabled: isRemoved,
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
                className={clsx('flex-shrink-0', isRemoved ? 'cursor-default' : 'cursor-move')}
                {...(isRemoved ? {} : listeners)}
            >
                <IconDrag className={clsx('text-lg', isRemoved ? 'text-muted' : 'text-orange-500')} />
            </div>
            <LemonBadge.Number count={order + 1} maxDigits={3} status="muted" />
            <div className={clsx('flex-1 min-w-0 flex flex-col gap-1', isRemoved && 'line-through opacity-50')}>
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
            {isRemoved ? (
                <LemonButton size="small" type="secondary" onClick={onRestore}>
                    Restore
                </LemonButton>
            ) : (
                <LemonButton
                    size="small"
                    status="danger"
                    type="secondary"
                    onClick={onRemove}
                    disabledReason={!canRemove ? 'At least one metric is required' : undefined}
                >
                    Remove
                </LemonButton>
            )}
        </div>
    )
}

export function MetricsReorderModal({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { isPrimaryMetricsReorderModalOpen, isSecondaryMetricsReorderModalOpen } = useValues(modalsLogic)
    const { closePrimaryMetricsReorderModal, closeSecondaryMetricsReorderModal } = useActions(modalsLogic)

    const isOpen = isSecondary ? isSecondaryMetricsReorderModalOpen : isPrimaryMetricsReorderModalOpen
    const closeModal = isSecondary ? closeSecondaryMetricsReorderModal : closePrimaryMetricsReorderModal

    const { experiment, getOrderedMetricsWithResults } = useValues(experimentLogic)
    const { updateExperiment } = useActions(experimentLogic)

    const [orderedUuids, setOrderedUuids] = useState<string[]>([])
    const [removedUuids, setRemovedUuids] = useState<Set<string>>(new Set())

    useEffect(() => {
        if (isOpen && experiment) {
            const currentOrder = isSecondary
                ? (experiment.secondary_metrics_ordered_uuids ?? [])
                : (experiment.primary_metrics_ordered_uuids ?? [])
            setOrderedUuids([...currentOrder])
            setRemovedUuids(new Set())
        } else {
            setOrderedUuids([])
            setRemovedUuids(new Set())
        }
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

    const activeCount = orderedUuids.length - removedUuids.size
    const canRemoveMore = isSecondary || activeCount > 1

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

    const handleSave = async (): Promise<void> => {
        const hasRemovals = removedUuids.size > 0

        if (!hasRemovals) {
            // No removals — just update ordering (existing behavior)
            if (isSecondary) {
                experiment!.secondary_metrics_ordered_uuids = orderedUuids
            } else {
                experiment!.primary_metrics_ordered_uuids = orderedUuids
            }

            await updateExperiment({
                primary_metrics_ordered_uuids: experiment?.primary_metrics_ordered_uuids,
                secondary_metrics_ordered_uuids: experiment?.secondary_metrics_ordered_uuids,
            })

            closeModal()
            return
        }

        // Build the update payload with removals
        const filteredOrderedUuids = orderedUuids.filter((uuid) => !removedUuids.has(uuid))

        // Determine which removed metrics are shared vs inline
        const metricsWithResults = getOrderedMetricsWithResults(isSecondary)
        const allMetrics = metricsWithResults.map(({ metric }: { metric: any }) => metric)
        const removedSharedMetricIds = new Set<number>()
        allMetrics.forEach((metric: any) => {
            const uuid = metric.uuid || metric.query?.uuid
            if (uuid && removedUuids.has(uuid) && metric.isSharedMetric && metric.sharedMetricId) {
                removedSharedMetricIds.add(metric.sharedMetricId)
            }
        })

        const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'
        const orderingField = isSecondary ? 'secondary_metrics_ordered_uuids' : 'primary_metrics_ordered_uuids'

        // Filter inline metrics to remove the deleted ones
        const currentInlineMetrics = (experiment?.[metricsField] || []) as ExperimentMetric[]
        const filteredInlineMetrics = currentInlineMetrics.filter((m) => !removedUuids.has(m.uuid!))

        const updatePayload: Record<string, any> = {
            [metricsField]: filteredInlineMetrics,
            [orderingField]: filteredOrderedUuids,
        }

        // If shared metrics were removed, update saved_metrics_ids
        if (removedSharedMetricIds.size > 0) {
            const filteredSavedMetrics = (experiment?.saved_metrics || [])
                .filter((sm) => !removedSharedMetricIds.has(sm.saved_metric))
                .map((sm) => ({
                    id: sm.saved_metric,
                    metadata: sm.metadata,
                }))
            updatePayload.saved_metrics_ids = filteredSavedMetrics
        }

        await updateExperiment(updatePayload)

        closeModal()
    }

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            width={600}
            title={`Reorder ${isSecondary ? 'secondary' : 'primary'} metrics`}
            description={<p>Drag and drop to reorder, or remove metrics you no longer need.</p>}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <DndContext modifiers={[restrictToVerticalAxis, restrictToParentElement]} onDragEnd={handleDragEnd}>
                    <SortableContext items={orderedUuids} strategy={verticalListSortingStrategy}>
                        {displayMetrics.length === 0 && (
                            <div className="p-4 text-center text-muted">
                                <p>No metrics available for reordering</p>
                            </div>
                        )}
                        {displayMetrics.map((metric, index) => {
                            const uuid = metric.uuid || (metric as any).query?.uuid
                            const isRemoved = removedUuids.has(uuid)
                            const effectiveIndex =
                                displayMetrics.slice(0, index + 1).filter((m) => {
                                    const id = m.uuid || (m as any).query?.uuid
                                    return !removedUuids.has(id)
                                }).length - 1
                            return (
                                <MetricItem
                                    key={uuid}
                                    metric={metric}
                                    order={isRemoved ? index : effectiveIndex}
                                    isRemoved={isRemoved}
                                    canRemove={canRemoveMore}
                                    onRemove={() => setRemovedUuids((prev) => new Set([...prev, uuid]))}
                                    onRestore={() =>
                                        setRemovedUuids((prev) => {
                                            const next = new Set(prev)
                                            next.delete(uuid)
                                            return next
                                        })
                                    }
                                />
                            )
                        })}
                    </SortableContext>
                </DndContext>
            </div>
        </LemonModal>
    )
}
