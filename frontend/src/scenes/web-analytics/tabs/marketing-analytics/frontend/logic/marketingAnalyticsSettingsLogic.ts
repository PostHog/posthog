import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { teamLogic } from 'scenes/teamLogic'
import { MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'

import { ConversionGoalFilter, MarketingAnalyticsConfig, SourceMap } from '~/queries/schema/schema-general'

import { generateUniqueName } from './utils'

import type { marketingAnalyticsSettingsLogicType } from './marketingAnalyticsSettingsLogicType'

const createEmptyConfig = (): MarketingAnalyticsConfig => ({
    sources_map: {},
    conversion_goals: [],
})

export const marketingAnalyticsSettingsLogic = kea<marketingAnalyticsSettingsLogicType>([
    path(['scenes', 'web-analytics', 'marketingAnalyticsSettingsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions({
        updateSourceMapping: (
            tableId: string,
            fieldName: MarketingAnalyticsColumnsSchemaNames,
            columnName: string | null
        ) => ({
            tableId,
            fieldName,
            columnName,
        }),
        updateConversionGoals: (conversionGoals: ConversionGoalFilter[]) => ({
            conversionGoals,
        }),
        addOrUpdateConversionGoal: (conversionGoal: ConversionGoalFilter) => ({
            conversionGoal,
        }),
        removeConversionGoal: (goalId: string) => ({
            goalId,
        }),
    }),
    reducers(({ values }) => ({
        marketingAnalyticsConfig: [
            null as MarketingAnalyticsConfig | null,
            {
                updateConversionGoals: (state: MarketingAnalyticsConfig | null, { conversionGoals }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), conversion_goals: conversionGoals }
                    }
                    return { ...state, conversion_goals: conversionGoals }
                },
                addOrUpdateConversionGoal: (state: MarketingAnalyticsConfig | null, { conversionGoal }) => {
                    if (!state) {
                        return { ...createEmptyConfig(), conversion_goals: [conversionGoal] }
                    }

                    const existingGoals = state.conversion_goals || []
                    const existingIndex = existingGoals.findIndex(
                        (goal) => goal.conversion_goal_id === conversionGoal.conversion_goal_id
                    )

                    let updatedConversionGoal = { ...conversionGoal }

                    // Check for name conflicts with other goals (excluding the current goal if updating)
                    const otherGoals =
                        existingIndex >= 0 ? existingGoals.filter((_, index) => index !== existingIndex) : existingGoals

                    const existingNames = otherGoals.map((goal) => goal.conversion_goal_name)
                    const uniqueName = generateUniqueName(conversionGoal.conversion_goal_name, existingNames)

                    updatedConversionGoal.conversion_goal_name = uniqueName

                    let updatedGoals: ConversionGoalFilter[]
                    if (existingIndex >= 0) {
                        // Update existing goal
                        updatedGoals = [...existingGoals]
                        updatedGoals[existingIndex] = updatedConversionGoal
                    } else {
                        // Add new goal
                        updatedGoals = [...existingGoals, updatedConversionGoal]
                    }

                    return { ...state, conversion_goals: updatedGoals }
                },
                removeConversionGoal: (state: MarketingAnalyticsConfig | null, { goalId }) => {
                    if (!state) {
                        return state
                    }

                    const existingGoals = state.conversion_goals || []
                    const updatedGoals = existingGoals.filter((goal) => goal.conversion_goal_id !== goalId)

                    return { ...state, conversion_goals: updatedGoals }
                },
                updateSourceMapping: (state: MarketingAnalyticsConfig | null, { tableId, fieldName, columnName }) => {
                    if (!state) {
                        return state
                    }

                    const updatedSourcesMap = { ...state.sources_map }
                    if (!updatedSourcesMap[tableId]) {
                        updatedSourcesMap[tableId] = {} as SourceMap
                    }

                    if (columnName === null) {
                        // Remove the field if columnName is undefined
                        delete updatedSourcesMap[tableId][fieldName]
                        // If source becomes empty, remove it entirely
                        if (Object.keys(updatedSourcesMap[tableId]).length === 0) {
                            delete updatedSourcesMap[tableId]
                        }
                    } else {
                        updatedSourcesMap[tableId] = {
                            ...updatedSourcesMap[tableId],
                            [fieldName]: columnName ?? undefined,
                        }
                    }
                    return { ...state, sources_map: updatedSourcesMap }
                },
            },
        ],
        savedMarketingAnalyticsConfig: [
            values.currentTeam?.marketing_analytics_config || createEmptyConfig(),
            {
                updateCurrentTeam: (_, { marketing_analytics_config }) => {
                    return marketing_analytics_config || createEmptyConfig()
                },
            },
        ],
    })),
    selectors({
        sources_map: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => marketingAnalyticsConfig?.sources_map || {},
        ],
        conversion_goals: [
            (s) => [s.marketingAnalyticsConfig],
            (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => {
                return marketingAnalyticsConfig?.conversion_goals || []
            },
        ],
    }),
    listeners(({ actions, values }) => {
        const updateCurrentTeam = (): void => {
            if (values.marketingAnalyticsConfig) {
                const payload = { marketing_analytics_config: values.marketingAnalyticsConfig }
                actions.updateCurrentTeam(payload)
            }
        }

        return {
            updateSourceMapping: updateCurrentTeam,
            updateConversionGoals: updateCurrentTeam,
            addOrUpdateConversionGoal: updateCurrentTeam,
            removeConversionGoal: updateCurrentTeam,
        }
    }),
    loaders(({ values }) => ({
        marketingAnalyticsConfig: {
            loadMarketingAnalyticsConfig: async () => {
                if (values.currentTeam) {
                    return values.currentTeam.marketing_analytics_config || createEmptyConfig()
                }
                return null
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMarketingAnalyticsConfig()
    }),
])
