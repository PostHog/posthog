import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic as enabledFlagLogic } from 'lib/logic/featureFlagLogic'
import { hasFormErrors, isObject } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTableNode, HogQLQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import {
    BaseMathType,
    Breadcrumb,
    FeatureFlagFilters,
    MultipleSurveyQuestion,
    PropertyFilterType,
    PropertyOperator,
    RatingSurveyQuestion,
    Survey,
    SurveyQuestionBase,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
    SurveyUrlMatchType,
} from '~/types'

import { defaultSurveyFieldValues, NEW_SURVEY, NewSurvey } from './constants'
import type { surveyLogicType } from './surveyLogicType'
import { surveysLogic } from './surveysLogic'
import { sanitizeHTML } from './utils'

export enum SurveyEditSection {
    Steps = 'steps',
    Widget = 'widget',
    Presentation = 'presentation',
    Appearance = 'appearance',
    Customization = 'customization',
    DisplayConditions = 'DisplayConditions',
    Scheduling = 'scheduling',
    CompletionConditions = 'CompletionConditions',
}
export interface SurveyLogicProps {
    /** Either a UUID or 'new'. */
    id: string
}

export interface SurveyMetricsQueries {
    surveysShown: DataTableNode
    surveysDismissed: DataTableNode
}

export interface SurveyUserStats {
    seen: number
    dismissed: number
    sent: number
}

export interface SurveyRatingResults {
    [key: number]: {
        data: number[]
        total: number
    }
}

export interface SurveyRecurringNPSResults {
    [key: number]: {
        data: number[]
        total: number
    }
}

type SurveyNPSResult = {
    Promoters: number
    Detractors: number
    Passives: number
}

export interface SurveySingleChoiceResults {
    [key: number]: {
        labels: string[]
        data: number[]
        total: number
    }
}

export interface SurveyMultipleChoiceResults {
    [key: number]: {
        labels: string[]
        data: number[]
    }
}

export interface SurveyOpenTextResults {
    [key: number]: {
        events: { distinct_id: string; properties: Record<string, any>; personProperties: Record<string, any> }[]
    }
}

export interface QuestionResultsReady {
    [key: string]: boolean
}

export type ScheduleType = 'once' | 'recurring'

const getResponseField = (i: number): string => (i === 0 ? '$survey_response' : `$survey_response_${i}`)

function duplicateExistingSurvey(survey: Survey | NewSurvey): Partial<Survey> {
    return {
        ...survey,
        id: NEW_SURVEY.id,
        name: `${survey.name} (copy)`,
        archived: false,
        start_date: null,
        end_date: null,
        targeting_flag_filters: survey.targeting_flag?.filters ?? NEW_SURVEY.targeting_flag_filters,
        linked_flag_id: survey.linked_flag?.id ?? NEW_SURVEY.linked_flag_id,
    }
}

export const surveyLogic = kea<surveyLogicType>([
    props({} as SurveyLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'surveys', 'surveyLogic', key]),
    connect(() => ({
        actions: [
            surveysLogic,
            ['loadSurveys'],
            eventUsageLogic,
            [
                'reportSurveyCreated',
                'reportSurveyLaunched',
                'reportSurveyEdited',
                'reportSurveyArchived',
                'reportSurveyStopped',
                'reportSurveyResumed',
                'reportSurveyViewed',
                'reportSurveyCycleDetected',
            ],
        ],
        values: [enabledFlagLogic, ['featureFlags as enabledFlags'], surveysLogic, ['surveys']],
    })),
    actions({
        setSurveyMissing: true,
        editingSurvey: (editing: boolean) => ({ editing }),
        setDefaultForQuestionType: (
            idx: number,
            type: SurveyQuestionType,
            isEditingQuestion: boolean,
            isEditingDescription: boolean,
            isEditingThankYouMessage: boolean
        ) => ({
            idx,
            type,
            isEditingQuestion,
            isEditingDescription,
            isEditingThankYouMessage,
        }),
        setQuestionBranchingType: (questionIndex, type, specificQuestionIndex) => ({
            questionIndex,
            type,
            specificQuestionIndex,
        }),
        setResponseBasedBranchingForQuestion: (questionIndex, responseValue, nextStep, specificQuestionIndex) => ({
            questionIndex,
            responseValue,
            nextStep,
            specificQuestionIndex,
        }),
        resetBranchingForQuestion: (questionIndex) => ({ questionIndex }),
        deleteBranchingLogic: true,
        archiveSurvey: true,
        setWritingHTMLDescription: (writingHTML: boolean) => ({ writingHTML }),
        setSurveyTemplateValues: (template: any) => ({ template }),
        setSelectedPageIndex: (idx: number | null) => ({ idx }),
        setSelectedSection: (section: SurveyEditSection | null) => ({ section }),

        setSchedule: (schedule: ScheduleType) => ({ schedule }),
        resetTargeting: true,
        setFlagPropertyErrors: (errors: any) => ({ errors }),
    }),
    loaders(({ props, actions, values }) => ({
        survey: {
            loadSurvey: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const survey = await api.surveys.get(props.id)
                        actions.reportSurveyViewed(survey)
                        return survey
                    } catch (error: any) {
                        if (error.status === 404) {
                            actions.setSurveyMissing()
                            return { ...NEW_SURVEY }
                        }
                        throw error
                    }
                }
                if (props.id === 'new' && router.values.hashParams.fromTemplate) {
                    return values.survey
                }
                return { ...NEW_SURVEY }
            },
            createSurvey: async (surveyPayload: Partial<Survey>) => {
                return await api.surveys.create(sanitizeQuestions(surveyPayload))
            },
            updateSurvey: async (surveyPayload: Partial<Survey>) => {
                return await api.surveys.update(props.id, sanitizeQuestions(surveyPayload))
            },
            launchSurvey: async () => {
                const startDate = dayjs()
                return await api.surveys.update(props.id, { start_date: startDate.toISOString() })
            },
            stopSurvey: async () => {
                return await api.surveys.update(props.id, { end_date: dayjs().toISOString() })
            },
            resumeSurvey: async () => {
                return await api.surveys.update(props.id, { end_date: null })
            },
        },
        duplicatedSurvey: {
            duplicateSurvey: async () => {
                const { survey } = values
                const payload = duplicateExistingSurvey(survey)
                const createdSurvey = await api.surveys.create(sanitizeQuestions(payload))

                lemonToast.success('Survey duplicated.', {
                    toastId: `survey-duplicated-${createdSurvey.id}`,
                    button: {
                        label: 'View Survey',
                        action: () => {
                            router.actions.push(urls.survey(createdSurvey.id))
                        },
                    },
                })

                actions.reportSurveyCreated(createdSurvey, true)
                return survey
            },
        },
        surveyUserStats: {
            loadSurveyUserStats: async (): Promise<SurveyUserStats> => {
                const survey: Survey = values.survey as Survey
                const startDate = dayjs(survey.start_date || survey.created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: hogql`
                        SELECT
                            (SELECT COUNT(DISTINCT person_id)
                                FROM events
                                WHERE event = 'survey shown'
                                    AND properties.$survey_id = ${props.id}
                                    AND timestamp >= ${startDate}
                                    AND timestamp <= ${endDate}),
                            (SELECT COUNT(DISTINCT person_id)
                                FROM events
                                WHERE event = 'survey dismissed'
                                    AND properties.$survey_id = ${props.id}
                                    AND timestamp >= ${startDate}
                                    AND timestamp <= ${endDate}),
                            (SELECT COUNT(DISTINCT person_id)
                                FROM events
                                WHERE event = 'survey sent'
                                    AND properties.$survey_id = ${props.id}
                                    AND timestamp >= ${startDate}
                                    AND timestamp <= ${endDate})
                    `,
                }
                const responseJSON = await api.query(query)
                const { results } = responseJSON
                if (results && results[0]) {
                    const [totalSeen, dismissed, sent] = results[0]
                    const onlySeen = totalSeen - dismissed - sent
                    return { seen: onlySeen < 0 ? 0 : onlySeen, dismissed, sent }
                }
                return { seen: 0, dismissed: 0, sent: 0 }
            },
        },
        surveyRatingResults: {
            loadSurveyRatingResults: async ({
                questionIndex,
                iteration,
            }: {
                questionIndex: number
                iteration?: number | null | undefined
            }): Promise<SurveyRatingResults> => {
                const question = values.survey.questions[questionIndex]
                if (question.type !== SurveyQuestionType.Rating) {
                    throw new Error(`Survey question type must be ${SurveyQuestionType.Rating}`)
                }

                const survey: Survey = values.survey as Survey
                const startDate = dayjs(survey.start_date || survey.created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                let iterationCondition = ''
                if (iteration && iteration > 0) {
                    iterationCondition = ` AND properties.$survey_iteration='${iteration}' `
                }
                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        SELECT
                            JSONExtractString(properties, '${getResponseField(questionIndex)}') AS survey_response,
                            COUNT(survey_response)
                        FROM events
                        WHERE event = 'survey sent' 
                            AND properties.$survey_id = '${props.id}'
                            ${iterationCondition}
                            AND timestamp >= '${startDate}'
                            AND timestamp <= '${endDate}'
                        GROUP BY survey_response
                    `,
                }
                const responseJSON = await api.query(query)
                // TODO:Dylan - I don't like how we lose our types here
                // would be cool if we could parse this in a more type-safe way
                const { results } = responseJSON

                let total = 0
                const dataSize = question.scale === 10 ? 11 : question.scale
                const data = new Array(dataSize).fill(0)
                results?.forEach(([value, count]) => {
                    total += count

                    const index = question.scale === 10 ? value : value - 1
                    data[index] = count
                })

                return { ...values.surveyRatingResults, [questionIndex]: { total, data } }
            },
        },
        surveyRecurringNPSResults: {
            loadSurveyRecurringNPSResults: async ({
                questionIndex,
            }: {
                questionIndex: number
            }): Promise<SurveyRecurringNPSResults> => {
                const question = values.survey.questions[questionIndex]
                if (question.type !== SurveyQuestionType.Rating) {
                    throw new Error(`Survey question type must be ${SurveyQuestionType.Rating}`)
                }

                const survey: Survey = values.survey as Survey
                const startDate = dayjs(survey.start_date || survey.created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        SELECT
                            JSONExtractString(properties, '$survey_iteration') AS survey_iteration,
                            JSONExtractString(properties, '${getResponseField(questionIndex)}') AS survey_response,
                            COUNT(survey_response)
                        FROM events
                        WHERE event = 'survey sent'
                            AND properties.$survey_id = '${props.id}'
                            AND timestamp >= '${startDate}'
                            AND timestamp <= '${endDate}'
                        GROUP BY survey_response, survey_iteration
                    `,
                }

                const responseJSON = await api.query(query)
                const { results } = responseJSON
                let total = 100
                const data = new Array(survey.iteration_count).fill(0)

                const iterations = new Map<string, SurveyNPSResult>()

                results?.forEach(([iteration, response, count]) => {
                    let promoters = 0
                    let passives = 0
                    let detractors = 0

                    if (parseInt(response) >= 9) {
                        // a Promoter is someone who gives a survey response of 9 or 10
                        promoters += parseInt(count)
                    } else if (parseInt(response) > 6) {
                        // a Passive is someone who gives a survey response of 7 or 8
                        passives += parseInt(count)
                    } else {
                        // a Detractor is someone who gives a survey response of 0 - 6
                        detractors += parseInt(count)
                    }

                    if (iterations.has(iteration)) {
                        const currentValue = iterations.get(iteration)
                        if (currentValue !== undefined) {
                            currentValue.Detractors += detractors
                            currentValue.Promoters += promoters
                            currentValue.Passives += passives
                        }
                    } else {
                        iterations.set(iteration, {
                            Detractors: detractors,
                            Passives: passives,
                            Promoters: promoters,
                        })
                    }
                })

                iterations.forEach((value: SurveyNPSResult, key: string) => {
                    // NPS score is calculated with this formula
                    // (Promoters / (Promoters + Passives + Detractors) * 100) - (Detractors / (Promoters + Passives + Detractors)* 100)
                    const totalResponses = value.Promoters + value.Passives + value.Detractors
                    const npsScore =
                        (value.Promoters / totalResponses) * 100 - (value.Detractors / totalResponses) * 100
                    data[parseInt(key) - 1] = npsScore
                    total += 100
                })

                return { ...values.surveyRecurringNPSResults, [questionIndex]: { total, data } }
            },
        },
        surveySingleChoiceResults: {
            loadSurveySingleChoiceResults: async ({
                questionIndex,
            }: {
                questionIndex: number
            }): Promise<SurveySingleChoiceResults> => {
                const survey: Survey = values.survey as Survey
                const startDate = dayjs(survey.start_date || survey.created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        SELECT
                            JSONExtractString(properties, '${getResponseField(questionIndex)}') AS survey_response,
                            COUNT(survey_response)
                        FROM events
                        WHERE event = 'survey sent' 
                            AND properties.$survey_id = '${props.id}'
                            AND timestamp >= '${startDate}'
                            AND timestamp <= '${endDate}'
                        GROUP BY survey_response
                    `,
                }
                const responseJSON = await api.query(query)
                const { results } = responseJSON

                const labels = results?.map((r) => r[0])
                const data = results?.map((r) => r[1])
                const total = data?.reduce((a, b) => a + b, 0)

                return { ...values.surveySingleChoiceResults, [questionIndex]: { labels, data, total } }
            },
        },
        surveyMultipleChoiceResults: {
            loadSurveyMultipleChoiceResults: async ({
                questionIndex,
            }: {
                questionIndex: number
            }): Promise<SurveyMultipleChoiceResults> => {
                const question = values.survey.questions[questionIndex]
                if (question.type !== SurveyQuestionType.MultipleChoice) {
                    throw new Error(`Survey question type must be ${SurveyQuestionType.MultipleChoice}`)
                }

                const survey: Survey = values.survey as Survey
                const startDate = dayjs(survey.start_date || survey.created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        SELECT 
                            count(),
                            arrayJoin(JSONExtractArrayRaw(properties, '${getResponseField(questionIndex)}')) AS choice
                        FROM events
                        WHERE event == 'survey sent'
                            AND properties.$survey_id == '${survey.id}'
                            AND timestamp >= '${startDate}'
                            AND timestamp <= '${endDate}'
                        GROUP BY choice
                        ORDER BY count() DESC
                    `,
                }
                const responseJSON = await api.query(query)
                let { results } = responseJSON

                // Remove outside quotes
                results = results?.map((r) => {
                    return [r[0], r[1].slice(1, r[1].length - 1)]
                })

                // Zero-fill choices that are not open-ended
                question.choices.forEach((choice, idx) => {
                    const isOpenChoice = idx == question.choices.length - 1 && question?.hasOpenChoice
                    if (results?.length && !isOpenChoice && !results.some((r) => r[1] === choice)) {
                        results.push([0, choice])
                    }
                })

                const data = results?.map((r) => r[0])
                const labels = results?.map((r) => r[1])

                return { ...values.surveyMultipleChoiceResults, [questionIndex]: { labels, data } }
            },
        },
        surveyOpenTextResults: {
            loadSurveyOpenTextResults: async ({
                questionIndex,
            }: {
                questionIndex: number
            }): Promise<SurveyOpenTextResults> => {
                const question = values.survey.questions[questionIndex]
                if (question.type !== SurveyQuestionType.Open) {
                    throw new Error(`Survey question type must be ${SurveyQuestionType.Open}`)
                }

                const survey: Survey = values.survey as Survey
                const startDate = dayjs(survey.start_date || survey.created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        SELECT distinct_id, properties, person.properties
                        FROM events
                        WHERE event == 'survey sent'
                            AND properties.$survey_id == '${survey.id}'
                            AND trim(JSONExtractString(properties, '${getResponseField(questionIndex)}')) != ''
                            AND timestamp >= '${startDate}'
                            AND timestamp <= '${endDate}'
                        LIMIT 20
                    `,
                }

                const responseJSON = await api.query(query)
                const { results } = responseJSON

                const events =
                    results?.map((r) => {
                        const distinct_id = r[0]
                        const properties = JSON.parse(r[1])
                        const personProperties = JSON.parse(r[2])
                        return { distinct_id, properties, personProperties }
                    }) || []

                return { ...values.surveyOpenTextResults, [questionIndex]: { events } }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        createSurveySuccess: ({ survey }) => {
            lemonToast.success(<>Survey {survey.name} created</>)
            actions.loadSurveys()
            router.actions.replace(urls.survey(survey.id))
            actions.reportSurveyCreated(survey)
        },
        updateSurveySuccess: ({ survey }) => {
            lemonToast.success(<>Survey {survey.name} updated</>)
            actions.editingSurvey(false)
            actions.reportSurveyEdited(survey)
            actions.loadSurveys()
        },
        duplicateSurveySuccess: () => {
            actions.loadSurveys()
        },
        launchSurveySuccess: ({ survey }) => {
            lemonToast.success(<>Survey {survey.name} launched</>)
            actions.loadSurveys()
            actions.reportSurveyLaunched(survey)
        },
        stopSurveySuccess: ({ survey }) => {
            actions.loadSurveys()
            actions.reportSurveyStopped(survey)
        },
        resumeSurveySuccess: ({ survey }) => {
            actions.loadSurveys()
            actions.reportSurveyResumed(survey)
        },
        archiveSurvey: () => {
            actions.updateSurvey({ archived: true })
        },
        loadSurveySuccess: () => {
            actions.loadSurveyUserStats()
        },
        resetTargeting: () => {
            actions.setSurveyValue('linked_flag_id', NEW_SURVEY.linked_flag_id)
            actions.setSurveyValue('targeting_flag_filters', NEW_SURVEY.targeting_flag_filters)
            actions.setSurveyValue('linked_flag', NEW_SURVEY.linked_flag)
            actions.setSurveyValue('targeting_flag', NEW_SURVEY.targeting_flag)
            actions.setSurveyValue('conditions', NEW_SURVEY.conditions)
            actions.setSurveyValue('remove_targeting_flag', true)
            actions.setSurveyValue('responses_limit', NEW_SURVEY.responses_limit)
            actions.setSurveyValues({
                iteration_count: NEW_SURVEY.iteration_count,
                iteration_frequency_days: NEW_SURVEY.iteration_frequency_days,
            })
        },
        submitSurveyFailure: async () => {
            // When errors occur, scroll to the error, but wait for errors to be set in the DOM first
            if (hasFormErrors(values.flagPropertyErrors) || values.urlMatchTypeValidationError) {
                actions.setSelectedSection(SurveyEditSection.DisplayConditions)
            } else {
                actions.setSelectedSection(SurveyEditSection.Steps)
            }
            setTimeout(
                () => document.querySelector(`.Field--error`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }),
                5
            )
        },
    })),
    reducers({
        isEditingSurvey: [
            false,
            {
                editingSurvey: (_, { editing }) => editing,
            },
        ],
        surveyMissing: [
            false,
            {
                setSurveyMissing: () => true,
            },
        ],

        survey: [
            { ...NEW_SURVEY } as NewSurvey | Survey,
            {
                setDefaultForQuestionType: (
                    state,
                    { idx, type, isEditingQuestion, isEditingDescription, isEditingThankYouMessage }
                ) => {
                    const question = isEditingQuestion
                        ? state.questions[idx].question
                        : defaultSurveyFieldValues[type].questions[0].question
                    const description = isEditingDescription
                        ? state.questions[idx].description
                        : defaultSurveyFieldValues[type].questions[0].description
                    const thankYouMessageHeader = isEditingThankYouMessage
                        ? state.appearance?.thankYouMessageHeader
                        : defaultSurveyFieldValues[type].appearance.thankYouMessageHeader
                    const newQuestions = [...state.questions]
                    newQuestions[idx] = {
                        ...state.questions[idx],
                        ...(defaultSurveyFieldValues[type].questions[0] as SurveyQuestionBase),
                        question,
                        description,
                    }
                    return {
                        ...state,
                        questions: newQuestions,
                        appearance: {
                            ...state.appearance,
                            ...defaultSurveyFieldValues[type].appearance,
                            thankYouMessageHeader,
                        },
                    }
                },
                setSurveyTemplateValues: (_, { template }) => {
                    const newTemplateSurvey = { ...NEW_SURVEY, ...template }
                    return newTemplateSurvey
                },
                setQuestionBranchingType: (state, { questionIndex, type, specificQuestionIndex }) => {
                    const newQuestions = [...state.questions]
                    const question = newQuestions[questionIndex]

                    if (type === SurveyQuestionBranchingType.NextQuestion) {
                        delete question.branching
                    } else if (type === SurveyQuestionBranchingType.End) {
                        question.branching = {
                            type: SurveyQuestionBranchingType.End,
                        }
                    } else if (type === SurveyQuestionBranchingType.ResponseBased) {
                        if (
                            question.type !== SurveyQuestionType.Rating &&
                            question.type !== SurveyQuestionType.SingleChoice
                        ) {
                            throw new Error(
                                `Survey question type must be ${SurveyQuestionType.Rating} or ${SurveyQuestionType.SingleChoice}`
                            )
                        }

                        question.branching = {
                            type: SurveyQuestionBranchingType.ResponseBased,
                            responseValues: {},
                        }
                    } else if (type === SurveyQuestionBranchingType.SpecificQuestion) {
                        question.branching = {
                            type: SurveyQuestionBranchingType.SpecificQuestion,
                            index: specificQuestionIndex,
                        }
                    }

                    newQuestions[questionIndex] = question
                    return {
                        ...state,
                        questions: newQuestions,
                    }
                },
                setResponseBasedBranchingForQuestion: (
                    state,
                    { questionIndex, responseValue, nextStep, specificQuestionIndex }
                ) => {
                    const newQuestions = [...state.questions]
                    const question = newQuestions[questionIndex]

                    if (
                        question.type !== SurveyQuestionType.Rating &&
                        question.type !== SurveyQuestionType.SingleChoice
                    ) {
                        throw new Error(
                            `Survey question type must be ${SurveyQuestionType.Rating} or ${SurveyQuestionType.SingleChoice}`
                        )
                    }

                    if (question.branching?.type !== SurveyQuestionBranchingType.ResponseBased) {
                        throw new Error(
                            `Survey question branching type must be ${SurveyQuestionBranchingType.ResponseBased}`
                        )
                    }

                    if ('responseValues' in question.branching) {
                        if (nextStep === SurveyQuestionBranchingType.NextQuestion) {
                            delete question.branching.responseValues[responseValue]
                        } else if (nextStep === SurveyQuestionBranchingType.End) {
                            question.branching.responseValues[responseValue] = SurveyQuestionBranchingType.End
                        } else if (nextStep === SurveyQuestionBranchingType.SpecificQuestion) {
                            question.branching.responseValues[responseValue] = specificQuestionIndex
                        }
                    }

                    newQuestions[questionIndex] = question
                    return {
                        ...state,
                        questions: newQuestions,
                    }
                },
                resetBranchingForQuestion: (state, { questionIndex }) => {
                    const newQuestions = [...state.questions]
                    const question = newQuestions[questionIndex]
                    delete question.branching

                    newQuestions[questionIndex] = question
                    return {
                        ...state,
                        questions: newQuestions,
                    }
                },
                deleteBranchingLogic: (state) => {
                    const newQuestions = [...state.questions]
                    newQuestions.forEach((question) => {
                        delete question.branching
                    })

                    return {
                        ...state,
                        questions: newQuestions,
                    }
                },
            },
        ],
        selectedPageIndex: [
            0 as number | null,
            {
                setSelectedPageIndex: (_, { idx }) => idx,
            },
        ],
        selectedSection: [
            SurveyEditSection.Steps as SurveyEditSection | null,
            {
                setSelectedSection: (_, { section }) => section,
            },
        ],
        surveyRatingResultsReady: [
            {},
            {
                loadSurveyRatingResultsSuccess: (state, { payload }) => {
                    if (!payload || !payload.hasOwnProperty('questionIndex')) {
                        return { ...state }
                    }
                    return { ...state, [payload.questionIndex]: true }
                },
            },
        ],
        surveyRecurringNPSResultsReady: [
            {},
            {
                loadSurveyRecurringNPSResultsSuccess: (state, { payload }) => {
                    if (!payload || !payload.hasOwnProperty('questionIndex')) {
                        return { ...state }
                    }
                    return { ...state, [payload.questionIndex]: true }
                },
            },
        ],
        surveySingleChoiceResultsReady: [
            {},
            {
                loadSurveySingleChoiceResultsSuccess: (state, { payload }) => {
                    if (!payload || !payload.hasOwnProperty('questionIndex')) {
                        return { ...state }
                    }
                    return { ...state, [payload.questionIndex]: true }
                },
            },
        ],
        surveyMultipleChoiceResultsReady: [
            {},
            {
                loadSurveyMultipleChoiceResultsSuccess: (state, { payload }) => {
                    if (!payload || !payload.hasOwnProperty('questionIndex')) {
                        return { ...state }
                    }
                    return { ...state, [payload.questionIndex]: true }
                },
            },
        ],
        surveyOpenTextResultsReady: [
            {},
            {
                loadSurveyOpenTextResultsSuccess: (state, { payload }) => {
                    if (!payload || !payload.hasOwnProperty('questionIndex')) {
                        return { ...state }
                    }
                    return { ...state, [payload.questionIndex]: true }
                },
            },
        ],
        writingHTMLDescription: [
            false,
            {
                setWritingHTMLDescription: (_, { writingHTML }) => writingHTML,
            },
        ],
        schedule: [
            'once',
            {
                setSchedule: (_, { schedule }) => schedule,
            },
        ],
        flagPropertyErrors: [
            null as any,
            {
                setFlagPropertyErrors: (_, { errors }) => errors,
            },
        ],
    }),
    selectors({
        isSurveyRunning: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                return !!(survey.start_date && !survey.end_date)
            },
        ],
        surveyShufflingQuestionsAvailable: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                return survey.questions.length > 1
            },
        ],
        showSurveyRepeatSchedule: [(s) => [s.schedule], (schedule: ScheduleType) => schedule == 'recurring'],
        descriptionContentType: [
            (s) => [s.survey],
            (survey: Survey) => (questionIndex: number) => {
                return survey.questions[questionIndex].descriptionContentType
            },
        ],
        surveyRepeatedActivationAvailable: [
            (s) => [s.survey],
            (survey: Survey): boolean =>
                survey.conditions?.events?.values != undefined && survey.conditions?.events?.values?.length > 0,
        ],
        hasTargetingSet: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                const hasLinkedFlag =
                    !!survey.linked_flag_id || (survey.linked_flag && Object.keys(survey.linked_flag).length > 0)
                const hasTargetingFlag =
                    (survey.targeting_flag && Object.keys(survey.targeting_flag).length > 0) ||
                    (survey.targeting_flag_filters && Object.keys(survey.targeting_flag_filters).length > 0)
                const hasOtherConditions = survey.conditions && Object.keys(survey.conditions).length > 0
                return !!hasLinkedFlag || !!hasTargetingFlag || !!hasOtherConditions
            },
        ],
        breadcrumbs: [
            (s) => [s.survey],
            (survey: Survey): Breadcrumb[] => [
                {
                    key: Scene.Surveys,
                    name: 'Surveys',
                    path: urls.surveys(),
                },
                { key: [Scene.Survey, survey?.id || 'new'], name: survey.name },
            ],
        ],
        dataTableQuery: [
            (s) => [s.survey],
            (survey): DataTableNode | null => {
                if (survey.id === 'new') {
                    return null
                }
                const surveyWithResults = survey as Survey
                const startDate = surveyWithResults.start_date || surveyWithResults.created_at
                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: [
                            '*',
                            ...survey.questions.map((q, i) => {
                                if (q.type === SurveyQuestionType.MultipleChoice) {
                                    // Join array items into a string
                                    return `coalesce(arrayStringConcat(JSONExtractArrayRaw(properties, '${getResponseField(
                                        i
                                    )}'), ', ')) -- ${q.question}`
                                }

                                return `coalesce(JSONExtractString(properties, '${getResponseField(i)}')) -- ${
                                    q.question
                                }`
                            }),
                            'timestamp',
                            'person',
                        ],
                        orderBy: ['timestamp DESC'],
                        where: [`event == 'survey sent'`],
                        after: startDate,
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$survey_id',
                                operator: PropertyOperator.Exact,
                                value: survey.id,
                            },
                        ],
                    },
                    propertiesViaUrl: true,
                    showExport: true,
                    showReload: true,
                    showEventFilter: false,
                    showPropertyFilter: true,
                    showTimings: false,
                }
            },
        ],
        targetingFlagFilters: [
            (s) => [s.survey],
            (survey): FeatureFlagFilters | undefined => {
                if (survey.targeting_flag_filters) {
                    return {
                        ...survey.targeting_flag_filters,
                        groups: survey.targeting_flag_filters.groups,
                        multivariate: null,
                        payloads: {},
                        super_groups: undefined,
                    }
                }
                return survey.targeting_flag?.filters || undefined
            },
        ],
        urlMatchTypeValidationError: [
            (s) => [s.survey],
            (survey): string | null => {
                if (survey.conditions?.urlMatchType === SurveyUrlMatchType.Regex && survey.conditions.url) {
                    try {
                        new RegExp(survey.conditions.url)
                    } catch (e: any) {
                        return e.message
                    }
                }
                return null
            },
        ],
        surveyNPSScore: [
            (s) => [s.surveyRatingResults],
            (surveyRatingResults) => {
                if (surveyRatingResults) {
                    const questionIdx = Object.keys(surveyRatingResults)[0]
                    const questionResults = surveyRatingResults[questionIdx]

                    // If we don't have any results, return 'No data available' instead of NaN.
                    if (questionResults.total === 0) {
                        return 'No data available'
                    }

                    const data: number[] = questionResults.data
                    if (data.length === 11) {
                        const promoters = data.slice(9, 11).reduce((a, b) => a + b, 0)
                        const passives = data.slice(7, 9).reduce((a, b) => a + b, 0)
                        const detractors = data.slice(0, 7).reduce((a, b) => a + b, 0)
                        const npsScore = ((promoters - detractors) / (promoters + passives + detractors)) * 100
                        return npsScore.toFixed(1)
                    }
                }
            },
        ],
        getBranchingDropdownValue: [
            (s) => [s.survey],
            (survey) => (questionIndex: number, question: RatingSurveyQuestion | MultipleSurveyQuestion) => {
                if (question.branching?.type) {
                    const { type } = question.branching

                    if (type === SurveyQuestionBranchingType.SpecificQuestion) {
                        const nextQuestionIndex = question.branching.index
                        return `${SurveyQuestionBranchingType.SpecificQuestion}:${nextQuestionIndex}`
                    }

                    return type
                }

                // No branching specified, default to Next question / Confirmation message
                if (questionIndex < survey.questions.length - 1) {
                    return SurveyQuestionBranchingType.NextQuestion
                }

                return SurveyQuestionBranchingType.End
            },
        ],
        getResponseBasedBranchingDropdownValue: [
            (s) => [s.survey],
            (survey) => (questionIndex: number, question: RatingSurveyQuestion | MultipleSurveyQuestion, response) => {
                if (!question.branching || !('responseValues' in question.branching)) {
                    return SurveyQuestionBranchingType.NextQuestion
                }

                // If a value is mapped onto an integer, we're redirecting to a specific question
                if (Number.isInteger(question.branching.responseValues[response])) {
                    const nextQuestionIndex = question.branching.responseValues[response]
                    return `${SurveyQuestionBranchingType.SpecificQuestion}:${nextQuestionIndex}`
                }

                // If any other value is present (practically only Confirmation message), return that value
                if (question.branching?.responseValues?.[response]) {
                    return question.branching.responseValues[response]
                }

                // No branching specified, default to Next question / Confirmation message
                if (questionIndex < survey.questions.length - 1) {
                    return SurveyQuestionBranchingType.NextQuestion
                }

                return SurveyQuestionBranchingType.End
            },
        ],
        hasCycle: [
            (s) => [s.survey],
            (survey) => {
                const graph = new Map()
                survey.questions.forEach((question, fromIndex: number) => {
                    if (!graph.has(fromIndex)) {
                        graph.set(fromIndex, new Set())
                    }

                    if (question.branching?.type === SurveyQuestionBranchingType.End) {
                        return
                    } else if (
                        question.branching?.type === SurveyQuestionBranchingType.SpecificQuestion &&
                        Number.isInteger(question.branching.index)
                    ) {
                        const toIndex = question.branching.index
                        graph.get(fromIndex).add(toIndex)
                        return
                    } else if (
                        question.branching?.type === SurveyQuestionBranchingType.ResponseBased &&
                        isObject(question.branching?.responseValues)
                    ) {
                        for (const [_, toIndex] of Object.entries(question.branching?.responseValues)) {
                            if (Number.isInteger(toIndex)) {
                                graph.get(fromIndex).add(toIndex)
                            }
                        }
                    }

                    // No branching - still need to connect the next question
                    if (fromIndex < survey.questions.length - 1) {
                        const toIndex = fromIndex + 1
                        graph.get(fromIndex).add(toIndex)
                    }
                })

                let cycleDetected = false
                function dfs(node: number, seen: number[]): void {
                    if (cycleDetected) {
                        return
                    }

                    for (const neighbor of graph.get(node) || []) {
                        if (seen.includes(neighbor)) {
                            cycleDetected = true
                            return
                        }
                        dfs(neighbor, seen.concat(neighbor))
                    }
                }
                dfs(0, [0])

                return cycleDetected
            },
        ],
        hasBranchingLogic: [
            (s) => [s.survey],
            (survey) =>
                survey.questions.some((question) => question.branching && Object.keys(question.branching).length > 0),
        ],
        surveyAsInsightURL: [
            (s) => [s.survey],
            (survey) => {
                const query: InsightVizNode = {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        properties: [
                            {
                                key: '$survey_id',
                                value: survey.id,
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                event: 'survey sent',
                                name: 'survey sent',
                                math: BaseMathType.TotalCount,
                            },
                            {
                                kind: NodeKind.EventsNode,
                                event: 'survey shown',
                                name: 'survey shown',
                                math: BaseMathType.TotalCount,
                            },
                            {
                                kind: NodeKind.EventsNode,
                                event: 'survey dismissed',
                                name: 'survey dismissed',
                                math: BaseMathType.TotalCount,
                            },
                        ],
                    },
                }

                return urls.insightNew(undefined, undefined, query)
            },
        ],
    }),
    forms(({ actions, props, values }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name, questions }) => ({
                // NOTE: When more validation errors are added, the submitSurveyFailure listener should be updated
                // to scroll to the right error section
                name: !name && 'Please enter a name.',
                questions: questions.map((question) => {
                    const questionErrors = {
                        question: !question.question && 'Please enter a question label.',
                    }

                    if (question.type === SurveyQuestionType.Rating) {
                        return {
                            ...questionErrors,
                            display: !question.display && 'Please choose a display type.',
                            scale: !question.scale && 'Please choose a scale.',
                            lowerBoundLabel: !question.lowerBoundLabel && 'Please enter a lower bound label.',
                            upperBoundLabel: !question.upperBoundLabel && 'Please enter an upper bound label.',
                        }
                    } else if (
                        question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice
                    ) {
                        return {
                            ...questionErrors,
                            choices: question.choices.some((choice) => !choice.trim())
                                ? 'Please ensure all choices are non-empty.'
                                : undefined,
                        }
                    }

                    return questionErrors
                }),
                // release conditions controlled using a PureField in the form
                targeting_flag_filters: values.flagPropertyErrors,
                // controlled using a PureField in the form
                urlMatchType: values.urlMatchTypeValidationError,
            }),
            submit: (surveyPayload) => {
                if (values.hasCycle) {
                    actions.reportSurveyCycleDetected(values.survey)

                    return lemonToast.error(
                        'Your survey contains an endless cycle. Please revisit your branching rules.'
                    )
                }

                // when the survey is being submitted, we should turn off editing mode
                actions.editingSurvey(false)
                if (props.id && props.id !== 'new') {
                    actions.updateSurvey(surveyPayload)
                } else {
                    actions.createSurvey(surveyPayload)
                }
            },
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.survey(props.id ?? 'new')]: (_, { edit }, __, { method }) => {
            // We always set the editingSurvey to true when we create a new survey
            if (props.id === 'new') {
                actions.editingSurvey(true)
            }
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadSurvey()
                } else {
                    actions.resetSurvey()
                }
            }

            if (edit) {
                actions.editingSurvey(true)
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setSurveyTemplateValues: () => {
            const hashParams = router.values.hashParams
            hashParams['fromTemplate'] = true

            return [urls.survey(values.survey.id), router.values.searchParams, hashParams]
        },
        editingSurvey: ({ editing }) => {
            const searchParams = router.values.searchParams
            if (editing) {
                searchParams['edit'] = true
            } else {
                delete searchParams['edit']
            }

            return [router.values.location.pathname, router.values.searchParams, router.values.hashParams]
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadSurvey()
        }
        if (props.id === 'new') {
            actions.resetSurvey()
        }
    }),
])

function sanitizeQuestions(surveyPayload: Partial<Survey>): Partial<Survey> {
    if (!surveyPayload.questions) {
        return surveyPayload
    }

    const sanitizedThankYouHeader = sanitizeHTML(surveyPayload.appearance?.thankYouMessageHeader || '')
    const sanitizedThankYouDescription = sanitizeHTML(surveyPayload.appearance?.thankYouMessageDescription || '')

    return {
        ...surveyPayload,
        questions: surveyPayload.questions?.map((rawQuestion) => {
            return {
                ...rawQuestion,
                description: sanitizeHTML(rawQuestion.description || ''),
                question: sanitizeHTML(rawQuestion.question || ''),
            }
        }),
        appearance: {
            ...surveyPayload.appearance,
            ...(sanitizedThankYouHeader && { thankYouMessageHeader: sanitizedThankYouHeader }),
            ...(sanitizedThankYouDescription && { thankYouMessageDescription: sanitizedThankYouDescription }),
        },
    }
}
