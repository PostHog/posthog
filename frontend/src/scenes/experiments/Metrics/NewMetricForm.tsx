import './TrendsMetricForm.scss'

import { LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { ExperimentQuery, NodeKind, ExperimentMetricType } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { commonActionFilterProps } from './Selectors'
import { metricQueryToFilter } from '../utils'

export function NewMetricForm({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { experiment, isExperimentRunning, editingPrimaryMetricIndex, editingSecondaryMetricIndex } =
        useValues(experimentLogic)
    const { setMetric } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex

    if (!metricIdx && metricIdx !== 0) {
        return <></>
    }

    // Cast to unknown first to avoid type errors when transitioning to the new ExperimentQuery type
    const currentMetric = metrics[metricIdx] as unknown as ExperimentQuery

    return (
        <>
            <div className="mb-4">
                <LemonLabel>Name (optional)</LemonLabel>
                <LemonInput
                    value={currentMetric.name}
                    onChange={(newName) => {
                        setMetric({
                            metricIdx,
                            name: newName,
                            metric: currentMetric.metric,
                            isSecondary,
                        })
                    }}
                />
            </div>
            <ActionFilter
                bordered
                filters={metricQueryToFilter(currentMetric)}
                setFilters={({ actions, events }: Partial<FilterType>): void => {
                    // We only support one event/action for experiment metrics
                    const entity = events?.[0] || actions?.[0]
                    if (entity) {
                        setMetric({
                            metricIdx,
                            name: currentMetric.name,
                            metric: {
                                kind: 'ExperimentMetric',
                                metric_type: ExperimentMetricType.COUNT,
                                metric_config: {
                                    kind: 'ExperimentEventMetricConfig',
                                    event: entity.id as string,
                                    math: entity.math,
                                    math_property: entity.math_property,
                                    math_hogql: entity.math_hogql,
                                },
                            },
                            isSecondary,
                        })
                    }
                }}
                typeKey="experiment-metric"
                buttonCopy="Add graph series"
                showSeriesIndicator={true}
                entitiesLimit={1}
                showNumericalPropsOnly={true}
                {...commonActionFilterProps}
            />
        </>
    )
}
