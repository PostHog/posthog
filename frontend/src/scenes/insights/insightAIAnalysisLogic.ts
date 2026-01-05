import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from '~/lib/api'
import { InsightQueryNode, InsightVizNode } from '~/queries/schema/schema-general'
import { organizationLogic } from '~/scenes/organizationLogic'
import { teamLogic } from '~/scenes/teamLogic'

import type { insightAIAnalysisLogicType } from './insightAIAnalysisLogicType'

export interface InsightSuggestion {
    title: string
    description?: string
    targetQuery: InsightVizNode
}

export interface InsightAIAnalysisLogicProps {
    insightId: number | undefined
    query: InsightQueryNode
}

export const insightAIAnalysisLogic = kea<insightAIAnalysisLogicType>([
    path(['scenes', 'insights', 'insightAIAnalysisLogic']),
    props({} as InsightAIAnalysisLogicProps),
    key((props) => props.insightId ?? 'new'),
    connect({
        values: [teamLogic, ['currentTeamId'], organizationLogic, ['currentOrganization']],
    }),
    actions({
        startAnalysis: true,
        setHasClickedAnalyze: (hasClicked: boolean) => ({ hasClicked }),
        resetAnalysis: true,
        reportAnalysisFeedback: (isPositive: boolean) => ({ isPositive }),
        reportSuggestionFeedback: (suggestionIndex: number, suggestionTitle: string, isPositive: boolean) => ({
            suggestionIndex,
            suggestionTitle,
            isPositive,
        }),
    }),
    loaders(({ props }) => ({
        analysis: [
            null as string | null,
            {
                startAnalysis: async () => {
                    if (!props.insightId) {
                        return null
                    }

                    try {
                        const response = await api.insights.analyze(props.insightId)
                        return response.result
                    } catch (e) {
                        console.error('[InsightAIAnalysis] Error fetching analysis', e)
                        return null
                    }
                },
            },
        ],
        suggestions: [
            [] as InsightSuggestion[],
            {
                loadSuggestions: async ({ analysisContext }: { analysisContext?: string }) => {
                    if (!props.insightId) {
                        return []
                    }

                    try {
                        const response = await api.insights.getSuggestions(props.insightId, analysisContext)
                        return response
                    } catch (e) {
                        console.error('[InsightAIAnalysis] Error fetching suggestions', e)
                        return []
                    }
                },
            },
        ],
    })),
    reducers({
        hasClickedAnalyze: [
            false,
            {
                setHasClickedAnalyze: (_, { hasClicked }) => hasClicked,
                resetAnalysis: () => false,
            },
        ],
    }),
    selectors({
        isAnalyzing: [(s) => [s.analysisLoading], (analysisLoading) => analysisLoading],
    }),
    listeners(({ actions, values, props }) => ({
        startAnalysis: () => {
            actions.setHasClickedAnalyze(true)
            posthog.capture('insight ai analysis started', {
                insight_id: props.insightId,
                insight_type: props.query.kind,
                team_id: values.currentTeamId,
                organization_id: values.currentOrganization?.id,
            })
        },
        reportAnalysisFeedback: ({ isPositive }) => {
            posthog.capture('insight ai analysis feedback', {
                insight_id: props.insightId,
                insight_type: props.query.kind,
                team_id: values.currentTeamId,
                organization_id: values.currentOrganization?.id,
                rating: isPositive ? 'good' : 'bad',
                analysis: values.analysis,
            })
        },
        reportSuggestionFeedback: ({ suggestionIndex, suggestionTitle, isPositive }) => {
            posthog.capture('insight ai suggestion feedback', {
                insight_id: props.insightId,
                insight_type: props.query.kind,
                team_id: values.currentTeamId,
                organization_id: values.currentOrganization?.id,
                suggestion_index: suggestionIndex,
                suggestion_title: suggestionTitle,
                rating: isPositive ? 'good' : 'bad',
            })
        },
        startAnalysisSuccess: () => {
            // When analysis completes, load suggestions with the analysis context
            if (values.analysis) {
                actions.loadSuggestions({ analysisContext: values.analysis })
            }
        },
        resetAnalysis: () => {
            // Reset suggestions when resetting analysis
            actions.loadSuggestionsSuccess([])
        },
    })),
])
