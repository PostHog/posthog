import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonTabs, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { ExperimentTrendsQuery, InsightQueryNode, NodeKind } from '~/queries/schema'
import { BaseMathType, ChartDisplayType, FilterType, PropertyMathType } from '~/types'

import { commonActionFilterProps } from '../Metrics/Selectors'
import { savedMetricLogic } from './savedMetricLogic'

export function SavedTrendsMetricForm(): JSX.Element {
    const { savedMetric } = useValues(savedMetricLogic)
    const { setSavedMetric } = useActions(savedMetricLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const [activeTab, setActiveTab] = useState('main')

    if (!savedMetric?.query) {
        return <></>
    }

    const savedMetricQuery = savedMetric.query as ExperimentTrendsQuery

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
                                <ActionFilter
                                    bordered
                                    filters={queryNodeToFilter(savedMetricQuery.count_query)}
                                    setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                                        const series = actionsAndEventsToSeries(
                                            { actions, events, data_warehouse } as any,
                                            true,
                                            MathAvailability.All
                                        )
                                        setSavedMetric({
                                            query: {
                                                ...savedMetricQuery,
                                                count_query: {
                                                    ...savedMetricQuery.count_query,
                                                    series,
                                                },
                                            },
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
                                        checked={(() => {
                                            const val = savedMetricQuery.count_query?.filterTestAccounts
                                            return hasFilters ? !!val : false
                                        })()}
                                        onChange={(checked: boolean) => {
                                            setSavedMetric({
                                                query: {
                                                    ...savedMetricQuery,
                                                    count_query: {
                                                        ...savedMetricQuery.count_query,
                                                        filterTestAccounts: checked,
                                                    },
                                                },
                                            })
                                        }}
                                        fullWidth
                                    />
                                </div>
                                <LemonBanner type="info" className="mt-3 mb-3">
                                    Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of data.
                                    This can cause a mismatch between the preview and the actual results.
                                </LemonBanner>
                                <div className="mt-4">
                                    <Query
                                        query={{
                                            kind: NodeKind.InsightVizNode,
                                            source: savedMetricQuery.count_query,
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
                                            !savedMetricQuery.exposure_query
                                                ? 'border-primary bg-primary-highlight'
                                                : 'border-border'
                                        }`}
                                        onClick={() => {
                                            setSavedMetric({
                                                query: {
                                                    ...savedMetricQuery,
                                                    exposure_query: undefined,
                                                },
                                            })
                                        }}
                                    >
                                        <div className="font-semibold flex justify-between items-center">
                                            <span>Default</span>
                                            {!savedMetricQuery.exposure_query && (
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
                                            savedMetricQuery.exposure_query
                                                ? 'border-primary bg-primary-highlight'
                                                : 'border-border'
                                        }`}
                                        onClick={() => {
                                            setSavedMetric({
                                                query: {
                                                    ...savedMetricQuery,
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
                                                            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                                                            explicitDate: true,
                                                        },
                                                        trendsFilter: {
                                                            display: ChartDisplayType.ActionsLineGraph,
                                                        },
                                                        filterTestAccounts: true,
                                                    },
                                                },
                                            })
                                        }}
                                    >
                                        <div className="font-semibold flex justify-between items-center">
                                            <span>Custom</span>
                                            {savedMetricQuery.exposure_query && (
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
                                {savedMetricQuery.exposure_query && (
                                    <>
                                        <ActionFilter
                                            bordered
                                            filters={queryNodeToFilter(
                                                savedMetricQuery.exposure_query as InsightQueryNode
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
                                                setSavedMetric({
                                                    query: {
                                                        ...savedMetricQuery,
                                                        exposure_query: {
                                                            ...savedMetricQuery.exposure_query,
                                                            series,
                                                        },
                                                    },
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
                                                    const val = savedMetricQuery.exposure_query?.filterTestAccounts
                                                    return hasFilters ? !!val : false
                                                })()}
                                                onChange={(checked: boolean) => {
                                                    setSavedMetric({
                                                        query: {
                                                            ...savedMetricQuery,
                                                            exposure_query: {
                                                                ...savedMetricQuery.exposure_query,
                                                                filterTestAccounts: checked,
                                                            },
                                                        },
                                                    })
                                                }}
                                                fullWidth
                                            />
                                        </div>
                                        <LemonBanner type="info" className="mt-3 mb-3">
                                            Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days
                                            of data. This can cause a mismatch between the preview and the actual
                                            results.
                                        </LemonBanner>
                                        <div className="mt-4">
                                            <Query
                                                query={{
                                                    kind: NodeKind.InsightVizNode,
                                                    source: savedMetricQuery.exposure_query,
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
