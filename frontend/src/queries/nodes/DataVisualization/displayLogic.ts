import * as d3 from 'd3'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { GoalLine } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from './dataVisualizationLogic'
import type { displayLogicType } from './displayLogicType'

export interface DisplayLogicProps {
    key: string
}

export const displayLogic = kea<displayLogicType>([
    key((props) => props.key),
    path(['queries', 'nodes', 'DataVisualization', 'displayLogic']),
    props({ key: '' } as DisplayLogicProps),
    connect(() => ({
        values: [dataVisualizationLogic, ['yData', 'query', 'chartSettings']],
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
