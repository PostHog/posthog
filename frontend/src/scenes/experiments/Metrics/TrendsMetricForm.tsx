import { IconCheckCircle } from '@posthog/icons'
import { LemonInput, LemonLabel, LemonTabs, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { useState } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { ExperimentTrendsQuery, InsightQueryNode, NodeKind } from '~/queries/schema'
import { BaseMathType, ChartDisplayType, FilterType, PropertyMathType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { commonActionFilterProps } from './Selectors'

export function TrendsMetricForm({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { experiment, isExperimentRunning, editingPrimaryMetricIndex, editingSecondaryMetricIndex } =
        useValues(experimentLogic)
    const { setTrendsMetric, setTrendsExposureMetric, setExperiment } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const [activeTab, setActiveTab] = useState('main')

    const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex

    if (!metricIdx && metricIdx !== 0) {
        return <></>
    }

    const currentMetric = metrics[metricIdx] as ExperimentTrendsQuery

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
                                            setTrendsMetric({
                                                metricIdx,
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

                                        setTrendsMetric({
                                            metricIdx,
                                            series,
                                            isSecondary,
                                        })
                                    }}
                                    typeKey="experiment-metric"
                                    buttonCopy="Add graph series"
                                    showSeriesIndicator={true}
                                    entitiesLimit={1}
                                    showNumericalPropsOnly={true}
                                    onlyPropertyMathDefinitions={[PropertyMathType.Average]}
                                    {...commonActionFilterProps}
                                />
                                <div className="mt-4 space-y-4">
                                    <TestAccountFilterSwitch
                                        checked={hasFilters ? !!currentMetric.count_query?.filterTestAccounts : false}
                                        onChange={(checked: boolean) => {
                                            setTrendsMetric({
                                                metricIdx,
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
                                    <div
                                        className={`flex-1 cursor-pointer p-4 rounded border ${
                                            !currentMetric.exposure_query
                                                ? 'border-primary bg-primary-highlight'
                                                : 'border-border'
                                        }`}
                                        onClick={() => {
                                            const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'
                                            setExperiment({
                                                ...experiment,
                                                [metricsField]: metrics.map((metric, idx) =>
                                                    idx === metricIdx
                                                        ? { ...metric, exposure_query: undefined }
                                                        : metric
                                                ),
                                            })
                                        }}
                                    >
                                        <div className="font-semibold flex justify-between items-center">
                                            <span>Default</span>
                                            {!currentMetric.exposure_query && (
                                                <IconCheckCircle fontSize={18} color="var(--primary)" />
                                            )}
                                        </div>
                                        <div className="text-muted text-sm leading-relaxed">
                                            Uses the number of unique users who trigger the{' '}
                                            <LemonTag>$feature_flag_called</LemonTag> event as your exposure count. This
                                            is the recommended setting for most experiments, as it accurately tracks
                                            variant exposure.
                                        </div>
                                    </div>
                                    <div
                                        className={`flex-1 cursor-pointer p-4 rounded border ${
                                            currentMetric.exposure_query
                                                ? 'border-primary bg-primary-highlight'
                                                : 'border-border'
                                        }`}
                                        onClick={() => {
                                            const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'
                                            setExperiment({
                                                ...experiment,
                                                [metricsField]: metrics.map((metric, idx) =>
                                                    idx === metricIdx
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
                                    >
                                        <div className="font-semibold flex justify-between items-center">
                                            <span>Custom</span>
                                            {currentMetric.exposure_query && (
                                                <IconCheckCircle fontSize={18} color="var(--primary)" />
                                            )}
                                        </div>
                                        <div className="text-muted text-sm leading-relaxed">
                                            Define your own exposure metric for specific use cases, such as counting by
                                            sessions instead of users. This gives you full control but requires careful
                                            configuration.
                                        </div>
                                    </div>
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

                                                setTrendsExposureMetric({
                                                    metricIdx,
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
                                        <div className="mt-4 space-y-4">
                                            <TestAccountFilterSwitch
                                                checked={(() => {
                                                    const val = currentMetric.exposure_query?.filterTestAccounts
                                                    return hasFilters ? !!val : false
                                                })()}
                                                onChange={(checked: boolean) => {
                                                    setTrendsExposureMetric({
                                                        metricIdx,
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
