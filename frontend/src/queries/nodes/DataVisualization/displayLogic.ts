import * as d3 from 'd3'
import { actions, afterMount, connect, kea, key, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { GoalLine } from '~/queries/schema'

import { dataVisualizationLogic } from './dataVisualizationLogic'
import type { displayLogicType } from './displayLogicType'

export interface DisplayLogicProps {
    key: string
}

export const displayLogic = kea<displayLogicType>([
    key((props) => props.key),
    path(['queries', 'nodes', 'DataVisualization', 'displayLogic']),
    props({ key: '' } as DisplayLogicProps),
    connect({
        values: [dataVisualizationLogic, ['yData', 'query']],
        actions: [dataVisualizationLogic, ['setQuery']],
    }),
    actions(({ values }) => ({
        addGoalLine: () => ({ yData: values.yData }),
        updateGoalLine: (goalLineIndex: number, key: string, value: string | number) => ({
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
                addGoalLine: (prev, { yData }) => {
                    const yDataFlat = yData?.flatMap((n) => n.data) ?? []
                    const yDataAvg = Math.round(d3.mean(yDataFlat) ?? 0)

                    prev.push({
                        label: 'Q4 Goal',
                        value: yDataAvg ?? 0,
                    })
                    return [...prev]
                },
                removeGoalLine: (prev, { goalLineIndex }) => {
                    prev.splice(goalLineIndex, 1)
                    return [...prev]
                },
                updateGoalLine: (prev, { goalLineIndex, key, value }) => {
                    if (key === 'value') {
                        if (Number.isNaN(value)) {
                            prev[goalLineIndex][key] = 0
                        } else {
                            prev[goalLineIndex][key] = parseInt(value.toString())
                        }
                    } else {
                        prev[goalLineIndex][key] = value
                    }

                    return [...prev]
                },
                setGoalLines: (_prev, { goalLines }) => {
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
    subscriptions(({ values, actions }) => ({
        goalLines: (value: GoalLine[]) => {
            const goalLines = value.length > 0 ? value : undefined

            actions.setQuery({
                ...values.query,
                chartSettings: {
                    ...values.query.chartSettings,
                    goalLines,
                },
            })
        },
    })),
])
