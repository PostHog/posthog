import * as d3 from 'd3'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { detectIntervalFromXData, findIncompleteRange } from 'scenes/insights/utils/incompletePeriodUtils'

import { ChartSettings, GoalLine, IncompletePeriodDisplay } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries, dataVisualizationLogic } from './dataVisualizationLogic'
import type { displayLogicType } from './displayLogicType'

export interface IncompletePeriodState {
    incompleteFrom: number
    incompleteTo: number
    trimCount: number
    shouldHide: boolean
    shouldDash: boolean
}

export const COMPLETE_STATE: IncompletePeriodState = {
    incompleteFrom: -1,
    incompleteTo: -1,
    trimCount: 0,
    shouldHide: false,
    shouldDash: false,
}

export interface DisplayLogicProps {
    key: string
}

export const displayLogic = kea<displayLogicType>([
    key((props) => props.key),
    path(['queries', 'nodes', 'DataVisualization', 'displayLogic']),
    props({ key: '' } as DisplayLogicProps),
    connect(() => ({
        values: [dataVisualizationLogic, ['xData', 'yData', 'query', 'chartSettings', 'visualizationType']],
        actions: [dataVisualizationLogic, ['setQuery', 'updateChartSettings', '_setQuery']],
    })),
    actions(({ values }) => ({
        addGoalLine: () => ({ yData: values.yData }),
        updateGoalLine: (goalLineIndex: number, key: string, value: string | number | boolean) => ({
            goalLineIndex,
            key,
            value,
        }),
        removeGoalLine: (goalLineIndex: number) => ({ goalLineIndex }),
        setGoalLines: (goalLines: GoalLine[]) => ({ goalLines }),
    })),
    reducers({
        goalLines: [
            [] as GoalLine[],
            {
                addGoalLine: (state, { yData }) => {
                    const yDataFlat = yData?.flatMap((n) => n.data) ?? []
                    const yDataAvg = Math.round(d3.mean(yDataFlat) ?? 0)

                    return [
                        ...state,
                        {
                            label: 'Q4 Goal',
                            value: yDataAvg ?? 0,
                            displayLabel: true,
                        },
                    ]
                },
                removeGoalLine: (state, { goalLineIndex }) => {
                    return state.filter((_, i) => i !== goalLineIndex)
                },
                updateGoalLine: (state, { goalLineIndex, key, value }) => {
                    return state.map((line, i) => (i === goalLineIndex ? { ...line, [key]: value } : line))
                },
                setGoalLines: (_state, { goalLines }) => {
                    return goalLines
                },
            },
        ],
    }),
    selectors({
        incompleteState: [
            (s) => [s.xData, s.chartSettings, s.visualizationType],
            (
                xData: AxisSeries<string> | null,
                chartSettings: ChartSettings,
                visualizationType: ChartDisplayType
            ): IncompletePeriodState => {
                const incompletePeriodDisplay: IncompletePeriodDisplay =
                    chartSettings.incompletePeriodDisplay ?? 'dashed'
                const isBarChart =
                    visualizationType === ChartDisplayType.ActionsBar ||
                    visualizationType === ChartDisplayType.ActionsStackedBar

                if (isBarChart || !xData?.data?.length) {
                    return COMPLETE_STATE
                }
                const interval = detectIntervalFromXData(xData.data)
                if (!interval) {
                    return COMPLETE_STATE
                }
                const range = findIncompleteRange(xData.data, interval)
                if (!range) {
                    return COMPLETE_STATE
                }
                return {
                    incompleteFrom: range.from,
                    incompleteTo: range.to,
                    trimCount: incompletePeriodDisplay === 'hidden' ? range.count : 0,
                    shouldHide: incompletePeriodDisplay === 'hidden',
                    shouldDash: incompletePeriodDisplay === 'dashed',
                }
            },
        ],
    }),
    listeners(({ actions }) => ({
        _setQuery: ({ node }) => {
            actions.setGoalLines(node.chartSettings?.goalLines ?? [])
        },
    })),
    afterMount(({ values, actions }) => {
        const chartSettings = values.query.chartSettings

        if (chartSettings?.goalLines) {
            actions.setGoalLines(chartSettings.goalLines)
        }
    }),
    subscriptions(({ actions, values }) => ({
        goalLines: (value: GoalLine[]) => {
            const currentGoalLines = values.chartSettings?.goalLines ?? []
            const newGoalLines = value.length > 0 ? value : []

            if (JSON.stringify(currentGoalLines) === JSON.stringify(newGoalLines)) {
                return
            }

            actions.updateChartSettings({ goalLines: value.length > 0 ? value : undefined })
        },
    })),
])
