import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ExperimentTrendsQuery, InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, FilterType } from '~/types'

import { commonActionFilterProps } from '../Metrics/Selectors'
import { LEGACY_EXPERIMENT_ALLOWED_MATH_TYPES } from '../constants'
import { sharedMetricLogic } from './sharedMetricLogic'

export function LegacySharedTrendsMetricForm(): JSX.Element {
    const { sharedMetric } = useValues(sharedMetricLogic)
    const { setSharedMetric } = useActions(sharedMetricLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const [activeTab, setActiveTab] = useState('main')

    if (!sharedMetric?.query) {
        return <></>
    }

    const sharedMetricQuery = sharedMetric.query as ExperimentTrendsQuery

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
                                    filters={queryNodeToFilter(sharedMetricQuery.count_query)}
                                    setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                                        const series = actionsAndEventsToSeries(
                                            { actions, events, data_warehouse } as any,
                                            true,
                                            MathAvailability.All
                                        )
                                        setSharedMetric({
                                            query: {
                                                ...sharedMetricQuery,
                                                count_query: {
                                                    ...sharedMetricQuery.count_query,
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
                                    allowedMathTypes={LEGACY_EXPERIMENT_ALLOWED_MATH_TYPES}
                                    {...commonActionFilterProps}
                                />
                                <div className="mt-4 deprecated-space-y-4">
                                    <TestAccountFilterSwitch
                                        checked={(() => {
                                            const val = sharedMetricQuery.count_query?.filterTestAccounts
                                            return hasFilters ? !!val : false
                                        })()}
                                        onChange={(checked: boolean) => {
                                            setSharedMetric({
                                                query: {
                                                    ...sharedMetricQuery,
                                                    count_query: {
                                                        ...sharedMetricQuery.count_query,
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
                                            source: sharedMetricQuery.count_query,
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
                                            !sharedMetricQuery.exposure_query
                                                ? 'border-accent bg-accent-highlight-secondary'
                                                : 'border-primary'
                                        }`}
                                        onClick={() => {
                                            setSharedMetric({
                                                query: {
                                                    ...sharedMetricQuery,
                                                    exposure_query: undefined,
                                                },
                                            })
                                        }}
                                    >
                                        <div className="font-semibold flex justify-between items-center">
                                            <span>Default</span>
                                            {!sharedMetricQuery.exposure_query && (
                                                <IconCheckCircle fontSize={18} color="var(--color-accent)" />
                                            )}
                                        </div>
                                        <div className="text-secondary text-sm leading-relaxed">
                                            Uses the number of unique users who trigger the{' '}
                                            <LemonTag>$feature_flag_called</LemonTag> event as your exposure count. This
                                            is the recommended setting for most experiments, as it accurately tracks
                                            variant exposure.
                                        </div>
                                    </div>
                                    <div
                                        className={`flex-1 cursor-pointer p-4 rounded border ${
                                            sharedMetricQuery.exposure_query
                                                ? 'border-accent bg-accent-highlight-secondary'
                                                : 'border-primary'
                                        }`}
                                        onClick={() => {
                                            setSharedMetric({
                                                query: {
                                                    ...sharedMetricQuery,
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
                                            {sharedMetricQuery.exposure_query && (
                                                <IconCheckCircle fontSize={18} color="var(--color-accent)" />
                                            )}
                                        </div>
                                        <div className="text-secondary text-sm leading-relaxed">
                                            Define your own exposure metric for specific use cases, such as counting by
                                            sessions instead of users. This gives you full control but requires careful
                                            configuration.
                                        </div>
                                    </div>
                                </div>
                                {sharedMetricQuery.exposure_query && (
                                    <>
                                        <ActionFilter
                                            bordered
                                            filters={queryNodeToFilter(
                                                sharedMetricQuery.exposure_query as InsightQueryNode
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
                                                setSharedMetric({
                                                    query: {
                                                        ...sharedMetricQuery,
                                                        exposure_query: {
                                                            ...sharedMetricQuery.exposure_query,
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
                                            allowedMathTypes={LEGACY_EXPERIMENT_ALLOWED_MATH_TYPES}
                                            {...commonActionFilterProps}
                                        />
                                        <div className="mt-4 deprecated-space-y-4">
                                            <TestAccountFilterSwitch
                                                checked={(() => {
                                                    const val = sharedMetricQuery.exposure_query?.filterTestAccounts
                                                    return hasFilters ? !!val : false
                                                })()}
                                                onChange={(checked: boolean) => {
                                                    setSharedMetric({
                                                        query: {
                                                            ...sharedMetricQuery,
                                                            exposure_query: {
                                                                ...sharedMetricQuery.exposure_query,
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
                                                    source: sharedMetricQuery.exposure_query,
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
