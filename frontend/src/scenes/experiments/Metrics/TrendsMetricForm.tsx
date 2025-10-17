import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonInput, LemonLabel, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ExperimentTrendsQuery, InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, FilterType } from '~/types'

import { SelectableCard } from '../components/SelectableCard'
import { LEGACY_EXPERIMENT_ALLOWED_MATH_TYPES } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { commonActionFilterProps } from './Selectors'

export function TrendsMetricForm({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { experiment, isExperimentRunning, editingPrimaryMetricUuid, editingSecondaryMetricUuid } =
        useValues(experimentLogic)
    const { setTrendsMetric, setTrendsExposureMetric, setExperiment } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const [activeTab, setActiveTab] = useState('main')

    const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const metricUuid = isSecondary ? editingSecondaryMetricUuid : editingPrimaryMetricUuid

    if (!metricUuid) {
        return <></>
    }

    const currentMetric = metrics.find((m) => m.uuid === metricUuid) as ExperimentTrendsQuery

    if (!currentMetric) {
        return <></>
    }

    const isDataWarehouseMetric = currentMetric.count_query?.series[0]?.kind === NodeKind.DataWarehouseNode

    return (
        <>
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                tabs={[
                    {
                        key: 'main',
                        label: 'Main metric',
                        content: (
                            <>
                                <div className="mb-4">
                                    <LemonLabel>Name (optional)</LemonLabel>
                                    <LemonInput
                                        value={currentMetric.name}
                                        onChange={(newName) => {
                                            if (!currentMetric.uuid) {
                                                return
                                            }
                                            setTrendsMetric({
                                                uuid: currentMetric.uuid,
                                                name: newName,
                                                isSecondary,
                                            })
                                        }}
                                    />
                                </div>
                                <ActionFilter
                                    bordered
                                    filters={queryNodeToFilter(currentMetric.count_query)}
                                    setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                                        const series = actionsAndEventsToSeries(
                                            { actions, events, data_warehouse } as any,
                                            true,
                                            MathAvailability.All
                                        )

                                        // Custom exposure metrics are not supported for data warehouse metrics
                                        if (series[0].kind === NodeKind.DataWarehouseNode) {
                                            const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'
                                            setExperiment({
                                                ...experiment,
                                                [metricsField]: metrics.map((metric) =>
                                                    metric.uuid === metricUuid
                                                        ? { ...metric, exposure_query: undefined }
                                                        : metric
                                                ),
                                            })
                                        }

                                        if (!currentMetric.uuid) {
                                            return
                                        }
                                        setTrendsMetric({
                                            uuid: currentMetric.uuid,
                                            series,
                                            isSecondary,
                                        })
                                    }}
                                    typeKey="experiment-metric"
                                    buttonCopy="Add graph series"
                                    showSeriesIndicator={true}
                                    entitiesLimit={1}
                                    showNumericalPropsOnly={true}
                                    allowedMathTypes={LEGACY_EXPERIMENT_ALLOWED_MATH_TYPES}
                                    {...commonActionFilterProps}
                                />
                                <div className="mt-4 deprecated-space-y-4">
                                    <TestAccountFilterSwitch
                                        checked={hasFilters ? !!currentMetric.count_query?.filterTestAccounts : false}
                                        onChange={(checked: boolean) => {
                                            if (!currentMetric.uuid) {
                                                return
                                            }
                                            setTrendsMetric({
                                                uuid: currentMetric.uuid,
                                                filterTestAccounts: checked,
                                                isSecondary,
                                            })
                                        }}
                                        fullWidth
                                    />
                                </div>
                                {isExperimentRunning && (
                                    <LemonBanner type="info" className="mt-3 mb-3">
                                        Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of
                                        data. This can cause a mismatch between the preview and the actual results.
                                    </LemonBanner>
                                )}
                                <div className="mt-4">
                                    <Query
                                        query={{
                                            kind: NodeKind.InsightVizNode,
                                            source: currentMetric.count_query,
                                            showTable: false,
                                            showLastComputation: true,
                                            showLastComputationRefresh: false,
                                        }}
                                        readOnly
                                    />
                                </div>
                            </>
                        ),
                    },
                    {
                        key: 'exposure',
                        label: 'Exposure',
                        content: (
                            <>
                                <div className="flex gap-4 mb-4">
                                    <SelectableCard
                                        title="Default"
                                        description={
                                            <>
                                                Uses the number of unique users who trigger the{' '}
                                                <LemonTag>$feature_flag_called</LemonTag> event as your exposure count.
                                                This is the recommended setting for most experiments, as it accurately
                                                tracks variant exposure.
                                            </>
                                        }
                                        selected={!currentMetric.exposure_query}
                                        onClick={() => {
                                            const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'
                                            setExperiment({
                                                ...experiment,
                                                [metricsField]: metrics.map((metric) =>
                                                    metric.uuid === metricUuid
                                                        ? { ...metric, exposure_query: undefined }
                                                        : metric
                                                ),
                                            })
                                        }}
                                    />
                                    <SelectableCard
                                        title="Custom"
                                        description="Define your own exposure metric for specific use cases, such as counting by sessions instead of users. This gives you full control but requires careful configuration."
                                        selected={!!currentMetric.exposure_query}
                                        {...(isDataWarehouseMetric
                                            ? {
                                                  disabled: true,
                                                  disabledReason:
                                                      'Custom exposure events are not supported for data warehouse metrics. Please contact support if you need this feature.',
                                              }
                                            : { disabled: false })}
                                        onClick={() => {
                                            const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'
                                            setExperiment({
                                                ...experiment,
                                                [metricsField]: metrics.map((metric) =>
                                                    metric.uuid === metricUuid
                                                        ? {
                                                              ...metric,
                                                              exposure_query: {
                                                                  kind: NodeKind.TrendsQuery,
                                                                  series: [
                                                                      {
                                                                          kind: NodeKind.EventsNode,
                                                                          name: '$feature_flag_called',
                                                                          event: '$feature_flag_called',
                                                                          math: BaseMathType.UniqueUsers,
                                                                      },
                                                                  ],
                                                                  interval: 'day',
                                                                  dateRange: {
                                                                      date_from: dayjs()
                                                                          .subtract(EXPERIMENT_DEFAULT_DURATION, 'day')
                                                                          .format('YYYY-MM-DDTHH:mm'),
                                                                      date_to: dayjs()
                                                                          .endOf('d')
                                                                          .format('YYYY-MM-DDTHH:mm'),
                                                                      explicitDate: true,
                                                                  },
                                                                  trendsFilter: {
                                                                      display: ChartDisplayType.ActionsLineGraph,
                                                                  },
                                                                  filterTestAccounts: true,
                                                              },
                                                          }
                                                        : metric
                                                ),
                                            })
                                        }}
                                    />
                                </div>
                                {currentMetric.exposure_query && (
                                    <>
                                        <ActionFilter
                                            bordered
                                            filters={queryNodeToFilter(
                                                currentMetric.exposure_query as InsightQueryNode
                                            )}
                                            setFilters={({
                                                actions,
                                                events,
                                                data_warehouse,
                                            }: Partial<FilterType>): void => {
                                                const series = actionsAndEventsToSeries(
                                                    { actions, events, data_warehouse } as any,
                                                    true,
                                                    MathAvailability.All
                                                )

                                                if (!currentMetric.uuid) {
                                                    return
                                                }
                                                setTrendsExposureMetric({
                                                    uuid: currentMetric.uuid,
                                                    series,
                                                    isSecondary,
                                                })
                                            }}
                                            typeKey="experiment-metric"
                                            buttonCopy="Add graph series"
                                            showSeriesIndicator={true}
                                            entitiesLimit={1}
                                            showNumericalPropsOnly={true}
                                            {...commonActionFilterProps}
                                        />
                                        <div className="mt-4 deprecated-space-y-4">
                                            <TestAccountFilterSwitch
                                                checked={(() => {
                                                    const val = currentMetric.exposure_query?.filterTestAccounts
                                                    return hasFilters ? !!val : false
                                                })()}
                                                onChange={(checked: boolean) => {
                                                    if (!currentMetric.uuid) {
                                                        return
                                                    }
                                                    setTrendsExposureMetric({
                                                        uuid: currentMetric.uuid,
                                                        filterTestAccounts: checked,
                                                        isSecondary,
                                                    })
                                                }}
                                                fullWidth
                                            />
                                        </div>
                                        {isExperimentRunning && (
                                            <LemonBanner type="info" className="mt-3 mb-3">
                                                Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION}{' '}
                                                days of data. This can cause a mismatch between the preview and the
                                                actual results.
                                            </LemonBanner>
                                        )}
                                        <div className="mt-4">
                                            <Query
                                                query={{
                                                    kind: NodeKind.InsightVizNode,
                                                    source: currentMetric.exposure_query,
                                                    showTable: false,
                                                    showLastComputation: true,
                                                    showLastComputationRefresh: false,
                                                }}
                                                readOnly
                                            />
                                        </div>
                                    </>
                                )}
                            </>
                        ),
                    },
                ]}
            />
        </>
    )
}
