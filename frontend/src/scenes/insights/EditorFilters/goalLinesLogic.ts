import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { GoalLine, HogQLQueryModifiers, TrendsQuery } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import type { goalLinesLogicType } from './goalLinesLogicType'

export type PoeModeTypes = HogQLQueryModifiers['personsOnEventsMode'] | null

export const goalLinesLogic = kea<goalLinesLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'goalLinesLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['querySource']],
        actions: [insightVizDataLogic(props), ['updateQuerySource']],
    })),
    actions(() => ({
        addGoalLine: true,
        updateGoalLine: (goalLineIndex: number, key: keyof GoalLine, value: NonNullable<GoalLine[keyof GoalLine]>) => ({
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
                addGoalLine: (state) => [...state, { label: 'Q4 Goal', value: 0, displayLabel: true }],
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
                removeGoalLine: (state, { goalLineIndex }) => {
                    const goalLines = [...state]
                    goalLines.splice(goalLineIndex, 1)
                    return goalLines
                },
                setGoalLines: (_, { goalLines }) => goalLines,
            },
        ],
    }),
    listeners(({ actions, values }) => {
        const updateQuerySource = (): void => {
            const querySource = values.querySource as TrendsQuery

            actions.updateQuerySource({
                trendsFilter: {
                    ...querySource?.trendsFilter,
                    goalLines: values.goalLines,
                },
            } as Partial<TrendsQuery>)
        }

        return {
            addGoalLine: updateQuerySource,
            updateGoalLine: updateQuerySource,
            removeGoalLine: updateQuerySource,
            setGoalLines: updateQuerySource,
        }
    }),
    subscriptions(({ values, actions }) => ({
        querySource: (querySource) => {
            const goalLines = querySource?.trendsFilter?.goalLines
            if (values.goalLines.length == 0 && goalLines && goalLines.length > 0) {
                actions.setGoalLines(goalLines)
            }
        },
    })),
])
