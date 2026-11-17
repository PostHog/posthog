import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import clsx from 'clsx'

import { verticalSortableListCollisionDetection } from 'lib/sortable'

import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'

import { MetricRowGroup } from './MetricRowGroup'
import { SortableMetricRowGroup } from './SortableMetricRowGroup'
import { TableHeader } from './TableHeader'
import { metricName, useMetricsTableModel } from './useMetricsTableModel'

interface MetricsTableProps {
    metrics: ExperimentMetric[]
    results: (NewExperimentQueryResponse | undefined)[]
    errors: any[]
    isSecondary: boolean
    showDetailsModal?: boolean
    /** Drops the table's own border so it can sit inside a parent panel. */
    embedded?: boolean
}

export function MetricsTable({
    metrics,
    results,
    errors,
    isSecondary,
    showDetailsModal = true,
    embedded = false,
}: MetricsTableProps): JSX.Element {
    const {
        experiment,
        exposuresLoading,
        axisRange,
        sectionLoading,
        statsMethod,
        sequentialTestingEnabled,
        sensors,
        orderedUuids,
        dragDisabled,
        handleDragEnd,
        announcements,
        handlersFor,
    } = useMetricsTableModel({ metrics, results, errors, isSecondary })

    if (metrics.length === 0) {
        return (
            <div className="p-8 text-center border rounded-md">
                <div className="text-muted">No {isSecondary ? 'secondary' : 'primary'} metrics configured</div>
            </div>
        )
    }

    return (
        <DndContext
            sensors={sensors}
            // Metric groups vary from one row to many, which is exactly where closestCenter misjudges.
            collisionDetection={verticalSortableListCollisionDetection}
            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
            // The wrapper is overflow-x-auto, which makes it a scroll container on both axes. Left to
            // auto-scroll it chases the dragged group past its own bounds, growing scrollHeight until
            // the rows scroll out of view. The page still scrolls normally.
            autoScroll={{ canScroll: (element) => element === document.scrollingElement }}
            accessibility={{ announcements }}
            onDragEnd={handleDragEnd}
        >
            <div className={clsx('w-full overflow-x-auto', !embedded && 'rounded-md border')}>
                <table className="w-full border-collapse text-sm">
                    <colgroup>
                        <col className="min-w-[200px]" />
                        <col />
                        <col />
                        <col />
                        <col />
                        <col />
                        <col className="min-w-[400px]" />
                    </colgroup>
                    <TableHeader
                        axisRange={axisRange}
                        statsMethod={statsMethod}
                        sequentialTestingEnabled={sequentialTestingEnabled}
                        loading={sectionLoading}
                    />
                    <SortableContext items={orderedUuids} strategy={verticalListSortingStrategy}>
                        {metrics.map((metric, index) => {
                            const result = results[index] ?? null
                            const error = errors[index]

                            const isLoading = !result && !error && isLaunched(experiment)

                            return (
                                <SortableMetricRowGroup
                                    key={metric.uuid || index}
                                    uuid={metric.uuid || String(index)}
                                    metricName={metricName(metric)}
                                    disabled={dragDisabled}
                                    isLastMetric={index === metrics.length - 1}
                                >
                                    {(dragHandle) => (
                                        <MetricRowGroup
                                            metric={metric}
                                            dragHandle={dragHandle}
                                            result={result}
                                            experiment={experiment}
                                            displayOrder={index}
                                            axisRange={axisRange}
                                            isSecondary={isSecondary}
                                            isLastMetric={index === metrics.length - 1}
                                            isAlternatingRow={index % 2 === 1}
                                            {...handlersFor(metric)}
                                            error={error}
                                            isLoading={isLoading}
                                            exposuresLoading={exposuresLoading}
                                            showDetailsModal={showDetailsModal}
                                        />
                                    )}
                                </SortableMetricRowGroup>
                            )
                        })}
                    </SortableContext>
                </table>
            </div>
        </DndContext>
    )
}
