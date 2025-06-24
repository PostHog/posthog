import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { teamLogic } from 'scenes/teamLogic'
import { MarketingAnalyticsSchema } from 'scenes/web-analytics/tabs/marketing-analytics/utils'

import { ConversionGoalFilter, MarketingAnalyticsConfig, SourceMap } from '~/queries/schema/schema-general'

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
        updateSourceMapping: (tableId: string, fieldName: MarketingAnalyticsSchema, columnName: string | null) => ({
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
                    
                    let updatedGoals: ConversionGoalFilter[]
                    if (existingIndex >= 0) {
                        // Update existing goal
                        updatedGoals = [...existingGoals]
                        updatedGoals[existingIndex] = conversionGoal
                    } else {
                        // Add new goal
                        updatedGoals = [...existingGoals, conversionGoal]
                    }
                    
                    return { ...state, conversion_goals: updatedGoals }
                },
                removeConversionGoal: (state: MarketingAnalyticsConfig | null, { goalId }) => {
                    if (!state) {
                        return state
                    }
                    
                    const existingGoals = state.conversion_goals || []
                    const updatedGoals = existingGoals.filter(
                        (goal) => goal.conversion_goal_id !== goalId
                    )
                    
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
                const goals = marketingAnalyticsConfig?.conversion_goals || []
                console.log('JFBW: marketingAnalyticsSettingsLogic conversion_goals selector', {
                    marketingAnalyticsConfig,
                    goals,
                    goalsCount: goals.length,
                    goalsDetailed: goals.map((goal: any, index: number) => ({
                        index,
                        goal,
                        goalType: typeof goal,
                        goalKeys: goal ? Object.keys(goal) : [],
                        goalId: goal?.conversion_goal_id,
                        schema: goal?.schema,
                        schemaType: typeof goal?.schema,
                        schemaKeys: goal?.schema ? Object.keys(goal.schema) : []
                    }))
                })
                return goals
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
                    const config = values.currentTeam.marketing_analytics_config || createEmptyConfig()
                    console.log('JFBW: loadMarketingAnalyticsConfig from team', {
                        currentTeam: values.currentTeam,
                        config,
                        configType: typeof config,
                        conversionGoals: config.conversion_goals,
                        conversionGoalsCount: config.conversion_goals?.length || 0,
                        conversionGoalsDetailed: config.conversion_goals?.map((goal: any, index: number) => ({
                            index,
                            goal,
                            goalType: typeof goal,
                            goalKeys: goal ? Object.keys(goal) : [],
                            goalId: goal?.conversion_goal_id,
                            schema: goal?.schema,
                            schemaType: typeof goal?.schema,
                            schemaKeys: goal?.schema ? Object.keys(goal.schema) : []
                        }))
                    })
                    return config
                }
                return null
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMarketingAnalyticsConfig()
    }),
])
