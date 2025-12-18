import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { ConversionGoal } from '~/queries/schema/schema-general'

import type { conversionGoalsLogicType } from './conversionGoalsLogicType'

export const conversionGoalsLogic = kea<conversionGoalsLogicType>([
    path(['scenes', 'settings', 'environment', 'conversionGoalsLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        addConversionGoal: (goal: ConversionGoal) => ({ goal }),
        updateConversionGoal: (goal: ConversionGoal) => ({ goal }),
        removeConversionGoal: (goalId: string) => ({ goalId }),
        setEditingGoalId: (goalId: string | null) => ({ goalId }),
    }),
    reducers({
        editingGoalId: [
            null as string | null,
            {
                setEditingGoalId: (_, { goalId }) => goalId,
            },
        ],
    }),
    selectors({
        conversionGoals: [
            (s) => [s.currentTeam],
            (currentTeam): ConversionGoal[] => {
                return (currentTeam?.extra_settings?.conversion_goals as ConversionGoal[]) || []
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        addConversionGoal: ({ goal }) => {
            const existingGoals = values.conversionGoals
            const newGoals = [...existingGoals, goal]
            actions.updateCurrentTeam({
                extra_settings: {
                    ...values.currentTeam?.extra_settings,
                    conversion_goals: newGoals,
                },
            })
        },
        updateConversionGoal: ({ goal }) => {
            const existingGoals = values.conversionGoals
            const newGoals = existingGoals.map((g) => (g.id === goal.id ? goal : g))
            actions.updateCurrentTeam({
                extra_settings: {
                    ...values.currentTeam?.extra_settings,
                    conversion_goals: newGoals,
                },
            })
        },
        removeConversionGoal: ({ goalId }) => {
            const existingGoals = values.conversionGoals
            const newGoals = existingGoals.filter((g) => g.id !== goalId)
            actions.updateCurrentTeam({
                extra_settings: {
                    ...values.currentTeam?.extra_settings,
                    conversion_goals: newGoals,
                },
            })
            actions.setEditingGoalId(null)
        },
    })),
])
