import { afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { Survey, SurveyEventProperties } from '~/types'

import { aiObservabilityTraceDataLogic } from '../aiObservabilityTraceDataLogic'
import type { feedbackViewLogicType } from './feedbackViewLogicType'

export interface FeedbackViewLogicProps {
    traceId: string
}

export const feedbackViewLogic = kea<feedbackViewLogicType>([
    path(['scenes', 'ai-observability', 'feedbackViewLogic']),
    props({} as FeedbackViewLogicProps),
    key((props) => props.traceId),
    connect({
        values: [aiObservabilityTraceDataLogic, ['trace']],
    }),
    loaders(({ props, values }) => ({
        surveyEvents: [
            null as LLMTraceEvent[] | null,
            {
                loadSurveyEvents: async (createdAt: string) => {
                    const date = dayjs(createdAt)
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT uuid, event, timestamp, properties
                            FROM events
                            WHERE (event = 'survey sent' OR event = 'survey shown')
                                AND properties.$ai_trace_id = ${props.traceId}
                                AND timestamp >= ${date}
                            ORDER BY if(event = 'survey sent', 0, 1)
                            LIMIT 1 BY properties.$survey_id
                        `,
                        { productKey: 'llm_analytics' }
                    )

                    return response.results.map(([uuid, event, timestamp, properties]: any) => ({
                        id: uuid,
                        event,
                        createdAt: timestamp,
                        properties: typeof properties === 'string' ? JSON.parse(properties) : properties,
                    }))
                },
            },
        ],
        surveys: [
            {} as Record<string, Survey>,
            {
                loadSurveys: async () => {
                    const surveyIds = values.surveyIds
                    if (surveyIds.length === 0) {
                        return {}
                    }
                    const response = await api.surveys.list({ ids: surveyIds.join(','), limit: surveyIds.length })
                    return Object.fromEntries(response.results.map((survey) => [survey.id, survey]))
                },
            },
        ],
    })),
    reducers({
        hasLoadingError: [
            false,
            {
                loadSurveyEventsFailure: () => true,
                loadSurveysFailure: () => true,
                loadSurveyEvents: () => false,
            },
        ],
    }),
    selectors({
        surveyIds: [
            (s) => [s.surveyEvents],
            (surveyEvents): string[] => {
                if (!surveyEvents) {
                    return []
                }
                const ids = new Set<string>()
                for (const event of surveyEvents) {
                    const surveyId = event.properties?.[SurveyEventProperties.SURVEY_ID]
                    if (surveyId) {
                        ids.add(surveyId)
                    }
                }
                return Array.from(ids)
            },
        ],
    }),
    listeners(({ actions }) => ({
        loadSurveyEventsSuccess: () => {
            actions.loadSurveys()
        },
    })),
    subscriptions(({ actions, values }) => ({
        trace: (trace: LLMTrace | undefined) => {
            if (trace?.createdAt && values.surveyEvents === null && !values.surveyEventsLoading) {
                actions.loadSurveyEvents(trace.createdAt)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        const trace = values.trace
        if (trace?.createdAt && values.surveyEvents === null && !values.surveyEventsLoading) {
            actions.loadSurveyEvents(trace.createdAt)
        }
    }),
])
