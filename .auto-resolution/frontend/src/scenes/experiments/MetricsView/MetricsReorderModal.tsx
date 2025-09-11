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
}: {
    metric: ExperimentMetric & { sharedMetricId?: number; isSharedMetric?: boolean }
    order: number
}): JSX.Element => {
    const uuid = metric.uuid || (metric as any).query?.uuid
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: uuid,
    })

    return (
        <div
            ref={setNodeRef}
            className={clsx(
                'relative flex items-center gap-2 p-3 border rounded cursor-move bg-bg-light',
                isDragging && 'z-[999999]'
            )}
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
            }}
            {...attributes}
            {...listeners}
        >
            <IconDrag className="text-orange-500 flex-shrink-0 text-lg" />
            <LemonBadge.Number count={order + 1} maxDigits={3} status="muted" />
            <div className="flex-1 min-w-0 flex flex-col gap-1">
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
        </div>
    )
}

export function MetricsReorderModal({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { isPrimaryMetricsReorderModalOpen, isSecondaryMetricsReorderModalOpen } = useValues(modalsLogic)
    const { closePrimaryMetricsReorderModal, closeSecondaryMetricsReorderModal } = useActions(modalsLogic)

    const isOpen = isSecondary ? isSecondaryMetricsReorderModalOpen : isPrimaryMetricsReorderModalOpen
    const closeModal = isSecondary ? closeSecondaryMetricsReorderModal : closePrimaryMetricsReorderModal

    const { experiment, getOrderedMetrics } = useValues(experimentLogic)
    const { updateExperiment } = useActions(experimentLogic)

    const [orderedUuids, setOrderedUuids] = useState<string[]>([])

    useEffect(() => {
        if (isOpen && experiment) {
            const currentOrder = isSecondary
                ? (experiment.secondary_metrics_ordered_uuids ?? [])
                : (experiment.primary_metrics_ordered_uuids ?? [])
            setOrderedUuids([...currentOrder])
        } else {
            setOrderedUuids([])
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

        const allMetrics = getOrderedMetrics(isSecondary)

        const metricsMap = new Map()
        allMetrics.forEach((metric: any) => {
            const uuid = metric.uuid || metric.query?.uuid
            if (uuid) {
                metricsMap.set(uuid, metric)
            }
        })

        return orderedUuids.map((uuid) => metricsMap.get(uuid)).filter(Boolean)
    })()

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

    const handleSaveOrder = async (): Promise<void> => {
        // Update the appropriate field and send both to preserve state
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
    }

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            width={600}
            title={`Reorder ${isSecondary ? 'secondary' : 'primary'} metrics`}
            description={
                <p>
                    Change the order in which your {isSecondary ? 'secondary' : 'primary'} metrics are displayed. You
                    can <b>drag and drop the metrics below</b> to change their order.
                </p>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSaveOrder}>
                        Save order
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
                        {displayMetrics.map((metric, index) => (
                            <MetricItem
                                key={metric.uuid || (metric as any).query?.uuid}
                                metric={metric}
                                order={index}
                            />
                        ))}
                    </SortableContext>
                </DndContext>
            </div>
        </LemonModal>
    )
}
