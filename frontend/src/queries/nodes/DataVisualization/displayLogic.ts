import * as d3 from 'd3'
import { actions, afterMount, connect, kea, key, path, props, reducers } from 'kea'
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
        actions: [dataVisualizationLogic, ['setQuery', 'updateChartSettings']],
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
                    const goalLines = [...state]

                    goalLines.splice(goalLineIndex, 1)
                    return goalLines
                },
                updateGoalLine: (state, { goalLineIndex, key, value }) => {
                    const goalLines = [...state]

                    if (key === 'value') {
                        if (Number.isNaN(value)) {
                            goalLines[goalLineIndex][key] = 0
                        } else {
                            goalLines[goalLineIndex][key] = parseInt(value.toString())
                        }
                    } else {
                        goalLines[goalLineIndex][key] = value
                    }

                    return goalLines
                },
                setGoalLines: (_state, { goalLines }) => {
                    return goalLines
                },
            },
        ],
    }),
    afterMount(({ values, actions }) => {
        const chartSettings = values.query.chartSettings

        if (chartSettings?.goalLines) {
            actions.setGoalLines(chartSettings.goalLines)
        }
    }),
    subscriptions(({ actions }) => ({
        goalLines: (value: GoalLine[]) => {
            const goalLines = value.length > 0 ? value : undefined

            actions.setQuery((query) => ({
                ...query,
                chartSettings: {
                    ...query.chartSettings,
                    goalLines,
                },
            }))
        },
    })),
])
