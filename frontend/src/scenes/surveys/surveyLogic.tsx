import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic as enabledFlagLogic } from 'lib/logic/featureFlagLogic'
import { allOperatorsMapping, debounce, hasFormErrors, isObject } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { CompareFilter, DataTableNode, HogQLQuery, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import {
    AnyPropertyFilter,
    BaseMathType,
    Breadcrumb,
    EventPropertyFilter,
    FeatureFlagFilters,
    IntervalType,
    MultipleSurveyQuestion,
    PropertyFilterType,
    PropertyOperator,
    RatingSurveyQuestion,
    Survey,
    SurveyMatchType,
    SurveyQuestionBase,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
    SurveySchedule,
} from '~/types'

import { defaultSurveyAppearance, defaultSurveyFieldValues, NEW_SURVEY, NewSurvey } from './constants'
import type { surveyLogicType } from './surveyLogicType'
import { surveysLogic } from './surveysLogic'
import {
    calculateNpsBreakdown,
    calculateNpsScore,
    getSurveyResponseKey,
    sanitizeHTML,
    sanitizeSurveyAppearance,
    validateColor,
} from './utils'

const DEFAULT_OPERATORS: Record<SurveyQuestionType, { label: string; value: PropertyOperator }> = {
    [SurveyQuestionType.Open]: {
        label: allOperatorsMapping[PropertyOperator.IContains],
        value: PropertyOperator.IContains,
    },
    [SurveyQuestionType.Rating]: {
        label: allOperatorsMapping[PropertyOperator.Exact],
        value: PropertyOperator.Exact,
    },
    [SurveyQuestionType.SingleChoice]: {
        label: allOperatorsMapping[PropertyOperator.Exact],
        value: PropertyOperator.Exact,
    },
    [SurveyQuestionType.MultipleChoice]: {
        label: allOperatorsMapping[PropertyOperator.IContains],
        value: PropertyOperator.IContains,
    },
    [SurveyQuestionType.Link]: {
        label: allOperatorsMapping[PropertyOperator.Exact],
        value: PropertyOperator.Exact,
    },
}

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

export type DataCollectionType = 'until_stopped' | 'until_limit' | 'until_adaptive_limit'

export interface SurveyDateRange {
    date_from: string | null
    date_to: string | null
}

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

const DATE_FORMAT = 'YYYY-MM-DDTHH:mm:ss'

function getSurveyStartDateForQuery(survey: Survey): string {
    return survey.start_date
        ? dayjs(survey.start_date).startOf('day').format(DATE_FORMAT)
        : dayjs(survey.created_at).startOf('day').format(DATE_FORMAT)
}

function getSurveyEndDateForQuery(survey: Survey): string {
    return survey.end_date
        ? dayjs(survey.end_date).endOf('day').format(DATE_FORMAT)
        : dayjs().endOf('day').format(DATE_FORMAT)
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
                'reportSurveyEdited',
                'reportSurveyArchived',
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
        setDataCollectionType: (dataCollectionType: DataCollectionType) => ({
            dataCollectionType,
        }),
        resetBranchingForQuestion: (questionIndex) => ({ questionIndex }),
        deleteBranchingLogic: true,
        archiveSurvey: true,
        setWritingHTMLDescription: (writingHTML: boolean) => ({ writingHTML }),
        setSurveyTemplateValues: (template: any) => ({ template }),
        setSelectedPageIndex: (idx: number | null) => ({ idx }),
        setSelectedSection: (section: SurveyEditSection | null) => ({ section }),
        resetTargeting: true,
        resetSurveyAdaptiveSampling: true,
        resetSurveyResponseLimits: true,
        setFlagPropertyErrors: (errors: any) => ({ errors }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
        setAnswerFilters: (filters: EventPropertyFilter[], reloadResults: boolean = true) => ({
            filters,
            reloadResults,
        }),
        setDateRange: (dateRange: SurveyDateRange) => ({ dateRange }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setCompareFilter: (compareFilter: CompareFilter | null) => ({ compareFilter }),
    }),
    loaders(({ props, actions, values }) => ({
        responseSummary: {
            summarize: async ({ questionIndex }: { questionIndex?: number }) => {
                return api.surveys.summarize_responses(props.id, questionIndex)
            },
        },
        survey: {
            loadSurvey: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const survey = await api.surveys.get(props.id)
                        actions.reportSurveyViewed(survey)
                        // Initialize answer filters for all questions
                        actions.setAnswerFilters(
                            survey.questions.map((question, index) => ({
                                key: getSurveyResponseKey(index),
                                operator: DEFAULT_OPERATORS[question.type].value,
                                type: PropertyFilterType.Event as const,
                                value: [],
                            })),
                            false
                        )
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
                    const templatedSurvey = values.survey
                    templatedSurvey.appearance = {
                        ...defaultSurveyAppearance,
                        ...teamLogic.values.currentTeam?.survey_config?.appearance,
                        ...templatedSurvey.appearance,
                    }
                    return templatedSurvey
                }

                const newSurvey = NEW_SURVEY
                newSurvey.appearance = {
                    ...defaultSurveyAppearance,
                    ...teamLogic.values.currentTeam?.survey_config?.appearance,
                    ...newSurvey.appearance,
                }

                return newSurvey
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
                const startDate = getSurveyStartDateForQuery(survey)
                const endDate = getSurveyEndDateForQuery(survey)

                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: hogql`
                        SELECT
                            (SELECT COUNT(DISTINCT person_id)
                                FROM events
                                WHERE event = 'survey shown'
                                    AND properties.$survey_id = ${props.id}
                                    AND timestamp >= ${startDate}
                                    AND timestamp <= ${endDate}
                                    AND {filters}),
                            (SELECT COUNT(DISTINCT person_id)
                                FROM events
                                WHERE event = 'survey dismissed'
                                    AND properties.$survey_id = ${props.id}
                                    AND timestamp >= ${startDate}
                                    AND timestamp <= ${endDate}
                                    AND {filters}),
                            (SELECT COUNT(DISTINCT person_id)
                                FROM events
                                WHERE event = 'survey sent'
                                    AND properties.$survey_id = ${props.id}
                                    AND timestamp >= ${startDate}
                                    AND timestamp <= ${endDate}
                                    AND {filters})
                    `,
                    filters: {
                        properties: [...values.propertyFilters, ...values.answerFilters],
                    },
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
            }: {
                questionIndex: number
            }): Promise<SurveyRatingResults> => {
                const question = values.survey.questions[questionIndex]
                if (question.type !== SurveyQuestionType.Rating) {
                    throw new Error(`Survey question type must be ${SurveyQuestionType.Rating}`)
                }

                const survey: Survey = values.survey as Survey
                const startDate = getSurveyStartDateForQuery(survey)
                const endDate = getSurveyEndDateForQuery(survey)

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
                            AND {filters}
                        GROUP BY survey_response
                    `,
                    filters: {
                        properties: [...values.propertyFilters, ...values.answerFilters],
                    },
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
                const startDate = getSurveyStartDateForQuery(survey)
                const endDate = getSurveyEndDateForQuery(survey)

                const query: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        SELECT
                            JSONExtractString(properties, '$survey_iteration') AS survey_iteration,
                            JSONExtractString(properties, '${getResponseField(questionIndex)}') AS survey_response,
                            COUNT(survey_response)
                        FROM events
                        WHERE event = 'survey sent'
                            AND properties.$survey_id = '${survey.id}'
                            AND timestamp >= '${startDate}'
                            AND timestamp <= '${endDate}'
                            AND {filters}
                        GROUP BY survey_response, survey_iteration
                    `,
                    filters: {
                        properties: [...values.propertyFilters, ...values.answerFilters],
                    },
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
                const startDate = getSurveyStartDateForQuery(survey)
                const endDate = getSurveyEndDateForQuery(survey)

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
                            AND {filters}
                        GROUP BY survey_response
                    `,
                    filters: {
                        properties: [...values.propertyFilters, ...values.answerFilters],
                    },
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
                const startDate = getSurveyStartDateForQuery(survey)
                const endDate = getSurveyEndDateForQuery(survey)

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
                            AND {filters}
                        GROUP BY choice
                        ORDER BY count() DESC
                    `,
                    filters: {
                        properties: [...values.propertyFilters, ...values.answerFilters],
                    },
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
                const startDate = getSurveyStartDateForQuery(survey)
                const endDate = getSurveyEndDateForQuery(survey)

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
                            AND {filters}
                        LIMIT 20
                    `,
                    filters: {
                        properties: [...values.propertyFilters, ...values.answerFilters],
                    },
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
    listeners(({ actions, values }) => {
        const reloadAllSurveyResults = debounce((): void => {
            // Load survey user stats
            actions.loadSurveyUserStats()

            // Load results for each question
            values.survey.questions.forEach((question, index) => {
                switch (question.type) {
                    case SurveyQuestionType.Rating:
                        actions.loadSurveyRatingResults({
                            questionIndex: index,
                        })
                        if (values.survey.iteration_count && values.survey.iteration_count > 0) {
                            actions.loadSurveyRecurringNPSResults({ questionIndex: index })
                        }
                        break
                    case SurveyQuestionType.SingleChoice:
                        actions.loadSurveySingleChoiceResults({ questionIndex: index })
                        break
                    case SurveyQuestionType.MultipleChoice:
                        actions.loadSurveyMultipleChoiceResults({ questionIndex: index })
                        break
                    case SurveyQuestionType.Open:
                        actions.loadSurveyOpenTextResults({ questionIndex: index })
                        break
                }
            })
        }, 1000)

        return {
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
            },
            stopSurveySuccess: () => {
                actions.loadSurveys()
            },
            resumeSurveySuccess: () => {
                actions.loadSurveys()
            },
            archiveSurvey: () => {
                actions.updateSurvey({ archived: true })
            },
            loadSurveySuccess: () => {
                actions.loadSurveyUserStats()

                if (values.survey.start_date) {
                    activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.LaunchSurvey)
                }

                const dateRange = {
                    date_from: getSurveyStartDateForQuery(values.survey as Survey),
                    date_to: getSurveyEndDateForQuery(values.survey as Survey),
                }
                actions.setDateRange(dateRange)
            },
            resetSurveyResponseLimits: () => {
                actions.setSurveyValue('responses_limit', null)
            },

            resetSurveyAdaptiveSampling: () => {
                actions.setSurveyValues({
                    response_sampling_interval: null,
                    response_sampling_interval_type: null,
                    response_sampling_limit: null,
                    response_sampling_start_date: null,
                    response_sampling_daily_limits: null,
                })
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
                actions.setFlagPropertyErrors(null)
            },
            submitSurveyFailure: async () => {
                // When errors occur, scroll to the error, but wait for errors to be set in the DOM first
                if (hasFormErrors(values.flagPropertyErrors) || values.urlMatchTypeValidationError) {
                    actions.setSelectedSection(SurveyEditSection.DisplayConditions)
                } else if (hasFormErrors(values.survey.appearance)) {
                    actions.setSelectedSection(SurveyEditSection.Customization)
                } else {
                    actions.setSelectedSection(SurveyEditSection.Steps)
                }
                setTimeout(
                    () =>
                        document
                            .querySelector(`.Field--error`)
                            ?.scrollIntoView({ block: 'center', behavior: 'smooth' }),
                    5
                )
            },
            setPropertyFilters: () => {
                reloadAllSurveyResults()
            },
            setAnswerFilters: ({ reloadResults }) => {
                if (reloadResults) {
                    reloadAllSurveyResults()
                }
            },
        }
    }),
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
        dataCollectionType: [
            'until_stopped' as DataCollectionType,
            {
                setDataCollectionType: (_, { dataCollectionType }) => dataCollectionType,
            },
        ],
        propertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { propertyFilters }) => propertyFilters,
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
        flagPropertyErrors: [
            null as any,
            {
                setFlagPropertyErrors: (_, { errors }) => errors,
            },
        ],
        answerFilters: [
            [] as EventPropertyFilter[],
            {
                setAnswerFilters: (_, { filters }) => filters,
            },
        ],
        dateRange: [
            null as SurveyDateRange | null,
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        interval: [
            null as IntervalType | null,
            {
                setInterval: (_, { interval }) => interval,
            },
        ],
        compareFilter: [
            null as CompareFilter | null,
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
            },
        ],
    }),
    selectors({
        isAnyResultsLoading: [
            (s) => [
                s.surveyUserStatsLoading,
                s.surveyRatingResultsReady,
                s.surveySingleChoiceResultsReady,
                s.surveyMultipleChoiceResultsReady,
                s.surveyOpenTextResultsReady,
                s.surveyRecurringNPSResultsReady,
            ],
            (
                surveyUserStatsLoading: boolean,
                surveyRatingResultsReady: boolean,
                surveySingleChoiceResultsReady: boolean,
                surveyMultipleChoiceResultsReady: boolean,
                surveyOpenTextResultsReady: boolean,
                surveyRecurringNPSResultsReady: boolean
            ) => {
                return (
                    surveyUserStatsLoading ||
                    !surveyRatingResultsReady ||
                    !surveySingleChoiceResultsReady ||
                    !surveyMultipleChoiceResultsReady ||
                    !surveyOpenTextResultsReady ||
                    !surveyRecurringNPSResultsReady
                )
            },
        ],
        isSurveyRunning: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                return !!(survey.start_date && !survey.end_date)
            },
        ],
        surveyUsesLimit: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                return !!(survey.responses_limit && survey.responses_limit > 0)
            },
        ],
        surveyUsesAdaptiveLimit: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                return !!(
                    survey.response_sampling_interval &&
                    survey.response_sampling_interval > 0 &&
                    survey.response_sampling_interval_type !== '' &&
                    survey.response_sampling_limit &&
                    survey.response_sampling_limit > 0
                )
            },
        ],
        surveyShufflingQuestionsAvailable: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                return survey.questions.length > 1
            },
        ],
        showSurveyRepeatSchedule: [(s) => [s.survey], (survey: Survey) => survey.schedule === SurveySchedule.Recurring],
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
            (s) => [s.survey, s.propertyFilters, s.answerFilters],
            (survey, propertyFilters, answerFilters): DataTableNode | null => {
                if (survey.id === 'new') {
                    return null
                }
                const surveyWithResults = survey as Survey

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
                            `coalesce(JSONExtractString(properties, '$lib_version')) -- Library Version`,
                            `coalesce(JSONExtractString(properties, '$lib')) -- Library`,
                            `coalesce(JSONExtractString(properties, '$current_url')) -- URL`,
                        ],
                        orderBy: ['timestamp DESC'],
                        where: [`event == 'survey sent'`],
                        after: getSurveyStartDateForQuery(surveyWithResults),
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$survey_id',
                                operator: PropertyOperator.Exact,
                                value: survey.id,
                            },
                            ...propertyFilters,
                            ...answerFilters,
                        ],
                    },
                    propertiesViaUrl: true,
                    showExport: true,
                    showReload: true,
                    showEventFilter: false,
                    showPropertyFilter: false,
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
                if (
                    survey.conditions?.url &&
                    [SurveyMatchType.Regex, SurveyMatchType.NotRegex].includes(
                        survey.conditions?.urlMatchType || SurveyMatchType.Exact
                    )
                ) {
                    try {
                        new RegExp(survey.conditions.url)
                    } catch (e: any) {
                        return e.message
                    }
                }
                return null
            },
        ],
        deviceTypesMatchTypeValidationError: [
            (s) => [s.survey],
            (survey: Survey): string | null => {
                if (
                    survey.conditions?.deviceTypes &&
                    [SurveyMatchType.Regex, SurveyMatchType.NotRegex].includes(
                        survey.conditions?.deviceTypesMatchType || SurveyMatchType.Exact
                    )
                ) {
                    try {
                        new RegExp(survey.conditions.deviceTypes?.at(0) || '')
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
                    if (!questionResults || questionResults.total === 0) {
                        return 'No data available'
                    }

                    const npsBreakdown = calculateNpsBreakdown(questionResults)
                    if (!npsBreakdown) {
                        return null
                    }

                    return calculateNpsScore(npsBreakdown).toFixed(1)
                }
            },
        ],
        npsBreakdown: [
            (s) => [s.surveyRatingResults],
            (surveyRatingResults) => {
                const surveyRatingKeys = Object.keys(surveyRatingResults ?? {})
                if (surveyRatingKeys.length === 0) {
                    return null
                }
                const questionIdx = surveyRatingKeys[0]
                const questionResults = surveyRatingResults?.[questionIdx]
                if (!questionResults) {
                    return null
                }

                return calculateNpsBreakdown(questionResults)
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

                return urls.insightNew({ query })
            },
        ],
        defaultInterval: [
            (s) => [s.survey],
            (survey: Survey): IntervalType => {
                const start = getSurveyStartDateForQuery(survey)
                const end = getSurveyEndDateForQuery(survey)
                const diffInDays = dayjs(end).diff(dayjs(start), 'days')
                const diffInWeeks = dayjs(end).diff(dayjs(start), 'weeks')

                if (diffInDays < 2) {
                    return 'hour'
                }
                if (diffInWeeks <= 4) {
                    return 'day'
                }
                if (diffInWeeks <= 12) {
                    return 'week'
                }
                return 'month'
            },
        ],
    }),
    forms(({ actions, props, values }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name, questions, appearance }) => {
                const sanitizedAppearance = sanitizeSurveyAppearance(appearance)
                return {
                    name: !name && 'Please enter a name.',
                    questions: questions.map((question) => {
                        const questionErrors = {
                            question: !question.question && 'Please enter a question label.',
                        }

                        if (question.type === SurveyQuestionType.Link) {
                            if (question.link) {
                                if (question.link.startsWith('mailto:')) {
                                    const emailRegex = /^mailto:[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
                                    if (!emailRegex.test(question.link)) {
                                        return {
                                            ...questionErrors,
                                            link: 'Please enter a valid mailto link (e.g., mailto:example@domain.com).',
                                        }
                                    }
                                } else {
                                    try {
                                        const url = new URL(question.link)
                                        if (url.protocol !== 'https:') {
                                            return {
                                                ...questionErrors,
                                                link: 'Only HTTPS links are supported for security reasons.',
                                            }
                                        }
                                    } catch {
                                        return {
                                            ...questionErrors,
                                            link: 'Please enter a valid HTTPS URL.',
                                        }
                                    }
                                }
                            }
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
                    appearance: sanitizedAppearance && {
                        backgroundColor: validateColor(sanitizedAppearance.backgroundColor, 'background color'),
                        borderColor: validateColor(sanitizedAppearance.borderColor, 'border color'),
                        ratingButtonActiveColor: validateColor(
                            sanitizedAppearance.ratingButtonActiveColor,
                            'rating button active color'
                        ),
                        ratingButtonColor: validateColor(sanitizedAppearance.ratingButtonColor, 'rating button color'),
                        submitButtonColor: validateColor(sanitizedAppearance.submitButtonColor, 'button color'),
                        submitButtonTextColor: validateColor(
                            sanitizedAppearance.submitButtonTextColor,
                            'button text color'
                        ),
                    },
                }
            },
            submit: (surveyPayload) => {
                if (values.hasCycle) {
                    actions.reportSurveyCycleDetected(values.survey)

                    return lemonToast.error(
                        'Your survey contains an endless cycle. Please revisit your branching rules.'
                    )
                }

                const payload = {
                    ...surveyPayload,
                    appearance: sanitizeSurveyAppearance(surveyPayload.appearance),
                }

                // when the survey is being submitted, we should turn off editing mode
                actions.editingSurvey(false)
                if (props.id && props.id !== 'new') {
                    actions.updateSurvey(payload)
                } else {
                    actions.createSurvey(payload)
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

    const appearance = {
        ...surveyPayload.appearance,
        ...(sanitizedThankYouHeader && { thankYouMessageHeader: sanitizedThankYouHeader }),
        ...(sanitizedThankYouDescription && { thankYouMessageDescription: sanitizedThankYouDescription }),
    }

    // Remove widget-specific fields if survey type is not Widget
    if (surveyPayload.type !== 'widget') {
        delete appearance.widgetType
        delete appearance.widgetLabel
        delete appearance.widgetColor
    }

    return {
        ...surveyPayload,
        questions: surveyPayload.questions?.map((rawQuestion) => {
            return {
                ...rawQuestion,
                description: sanitizeHTML(rawQuestion.description || ''),
                question: sanitizeHTML(rawQuestion.question || ''),
            }
        }),
        appearance,
    }
}
