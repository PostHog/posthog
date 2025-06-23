import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { openSaveToModal } from 'lib/components/SaveTo/saveToLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic as enabledFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { allOperatorsMapping, dateStringToDayJs, debounce, hasFormErrors, isObject } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'
import {
    branchingConfigToDropdownValue,
    canQuestionHaveResponseBasedBranching,
    createBranchingConfig,
    getDefaultBranchingType,
} from 'scenes/surveys/components/question-branching/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { MAX_SELECT_RETURNED_ROWS } from '~/queries/nodes/DataTable/DataTableExport'
import { CompareFilter, DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { HogQLQueryString } from '~/queries/utils'
import {
    AnyPropertyFilter,
    BaseMathType,
    Breadcrumb,
    EventPropertyFilter,
    FeatureFlagFilters,
    IntervalType,
    MultipleSurveyQuestion,
    ProjectTreeRef,
    PropertyFilterType,
    PropertyOperator,
    RatingSurveyQuestion,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyEventStats,
    SurveyMatchType,
    SurveyQuestion,
    SurveyQuestionBase,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
    SurveyRates,
    SurveySchedule,
    SurveyStats,
} from '~/types'

import {
    defaultSurveyAppearance,
    defaultSurveyFieldValues,
    NEW_SURVEY,
    NewSurvey,
    SURVEY_RATING_SCALE,
} from './constants'
import type { surveyLogicType } from './surveyLogicType'
import { surveysLogic } from './surveysLogic'
import {
    buildPartialResponsesFilter,
    calculateNpsBreakdown,
    createAnswerFilterHogQLExpression,
    DATE_FORMAT,
    getResponseFieldWithId,
    getSurveyEndDateForQuery,
    getSurveyResponse,
    getSurveyStartDateForQuery,
    isSurveyRunning,
    sanitizeSurvey,
    sanitizeSurveyAppearance,
    validateSurveyAppearance,
} from './utils'

export type SurveyBaseStatTuple = [string, number, number, string | null, string | null] // [event_name, total_count, unique_persons, first_seen, last_seen]
export type SurveyBaseStatsResult = SurveyBaseStatTuple[] | null
export type DismissedAndSentCountResult = number | null

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

function duplicateExistingSurvey(survey: Survey | NewSurvey): Partial<Survey> {
    return {
        ...survey,
        questions: survey.questions.map((question) => ({
            ...question,
            id: undefined,
        })),
        id: NEW_SURVEY.id,
        name: `${survey.name} (copy)`,
        archived: false,
        start_date: null,
        end_date: null,
        targeting_flag_filters: survey.targeting_flag?.filters ?? NEW_SURVEY.targeting_flag_filters,
        linked_flag_id: survey.linked_flag?.id ?? NEW_SURVEY.linked_flag_id,
    }
}

export interface ChoiceQuestionResponseData {
    label: string
    value: number
    isPredefined: boolean
}

export interface OpenQuestionResponseData {
    distinctId: string
    response: string
    personProperties?: Record<string, any>
}

export interface ChoiceQuestionProcessedResponses {
    type: SurveyQuestionType.SingleChoice | SurveyQuestionType.Rating | SurveyQuestionType.MultipleChoice
    data: ChoiceQuestionResponseData[]
    totalResponses: number
}

export interface OpenQuestionProcessedResponses {
    type: SurveyQuestionType.Open
    data: OpenQuestionResponseData[]
    totalResponses: number
}

export type QuestionProcessedResponses = ChoiceQuestionProcessedResponses | OpenQuestionProcessedResponses

interface ResponsesByQuestion {
    [questionId: string]: QuestionProcessedResponses
}

export interface ConsolidatedSurveyResults {
    responsesByQuestion: {
        [questionId: string]: QuestionProcessedResponses
    }
}

/**
 * Raw survey response data from the SQL query.
 * Each SurveyResponseRow represents one user's complete response to all questions.
 *
 * Structure:
 * - response[questionIndex] contains the answer to that specific question
 * - For rating/single choice/open questions: response[questionIndex] is a string
 * - For multiple choice questions: response[questionIndex] is a string[]
 * - The last elements may contain metadata like person properties and distinct_id
 *
 * Example:
 * [
 *   ["9", ["Customer case studies"], "Great product!", "user123"],
 *   ["7", ["Tutorials", "Other"], "Good but could improve", "user456"]
 * ]
 */
export type SurveyResponseRow = Array<string | string[]>
export type SurveyRawResults = SurveyResponseRow[]

function isEmptyOrUndefined(value: any): boolean {
    return value === null || value === undefined || value === ''
}

function isQuestionOpenChoice(question: SurveyQuestion, choiceIndex: number): boolean {
    if (question.type !== SurveyQuestionType.SingleChoice && question.type !== SurveyQuestionType.MultipleChoice) {
        return false
    }
    return !!(choiceIndex === question.choices.length - 1 && question?.hasOpenChoice)
}

// Extract question processors into separate functions for better maintainability
function processSingleChoiceQuestion(
    question: MultipleSurveyQuestion,
    questionIndex: number,
    results: SurveyRawResults
): ChoiceQuestionProcessedResponses {
    const counts: { [key: string]: number } = {}
    let total = 0

    // Zero-fill predefined choices (excluding open choice)
    question.choices?.forEach((choice: string, choiceIndex: number) => {
        if (!isQuestionOpenChoice(question, choiceIndex)) {
            counts[choice] = 0
        }
    })

    // Count responses
    results?.forEach((row: SurveyResponseRow) => {
        const value = row[questionIndex] as string
        if (!isEmptyOrUndefined(value)) {
            counts[value] = (counts[value] || 0) + 1
            total += 1
        }
    })

    const data = Object.entries(counts)
        .map(([label, value]) => ({
            label,
            value,
            isPredefined: question.choices?.includes(label) ?? false,
        }))
        .sort((a, b) => b.value - a.value)

    return {
        type: SurveyQuestionType.SingleChoice,
        data,
        totalResponses: total,
    }
}

function processRatingQuestion(
    question: RatingSurveyQuestion,
    questionIndex: number,
    results: SurveyRawResults
): ChoiceQuestionProcessedResponses {
    const scaleSize = question.scale === SURVEY_RATING_SCALE.NPS_10_POINT ? 11 : question.scale
    const counts = new Array(scaleSize).fill(0)
    let total = 0

    results?.forEach((row: SurveyResponseRow) => {
        const value = row[questionIndex] as string
        if (!isEmptyOrUndefined(value)) {
            const parsedValue = parseInt(value, 10)
            if (!isNaN(parsedValue)) {
                let arrayIndex: number
                let isValid = false

                if (question.scale === SURVEY_RATING_SCALE.NPS_10_POINT) {
                    // NPS scale: 0-10 (11 values)
                    isValid = parsedValue >= 0 && parsedValue <= 10
                    arrayIndex = parsedValue
                } else {
                    // Regular rating scales: 1-N (N values, but we use 0-based indexing)
                    // For a 5-point scale, accept ratings 1-5 and map them to indices 0-4
                    isValid = parsedValue >= 1 && parsedValue <= question.scale
                    arrayIndex = parsedValue - 1 // Convert 1-based to 0-based
                }

                if (isValid) {
                    counts[arrayIndex] += 1
                    total += 1
                }
            }
        }
    })

    const data = counts.map((count, index) => {
        // For display labels:
        // - NPS (scale 10): show 0-10
        // - Regular scales: show 1-N (convert from 0-based index)
        const label = question.scale === SURVEY_RATING_SCALE.NPS_10_POINT ? index.toString() : (index + 1).toString()

        return {
            label,
            value: count,
            isPredefined: true,
        }
    })

    return {
        type: SurveyQuestionType.Rating,
        data,
        totalResponses: total,
    }
}

function processMultipleChoiceQuestion(
    question: MultipleSurveyQuestion,
    questionIndex: number,
    results: SurveyRawResults
): ChoiceQuestionProcessedResponses {
    const counts: { [key: string]: number } = {}
    let total = 0

    // Zero-fill predefined choices (excluding open choice)
    question.choices?.forEach((choice: string, choiceIndex: number) => {
        if (!isQuestionOpenChoice(question, choiceIndex)) {
            counts[choice] = 0
        }
    })

    results?.forEach((row: SurveyResponseRow) => {
        const value = row[questionIndex] as string[]
        if (value !== null && value !== undefined) {
            total += 1
            value.forEach((choice) => {
                const cleaned = choice.replace(/^['"]+|['"]+$/g, '')
                if (!isEmptyOrUndefined(cleaned)) {
                    counts[cleaned] = (counts[cleaned] || 0) + 1
                }
            })
        }
    })

    const data = Object.entries(counts)
        .map(([label, value]) => ({
            label,
            value,
            isPredefined: question.choices?.includes(label) ?? false,
        }))
        .sort((a, b) => b.value - a.value)

    return {
        type: SurveyQuestionType.MultipleChoice,
        data,
        totalResponses: total,
    }
}

function processOpenQuestion(questionIndex: number, results: SurveyRawResults): OpenQuestionProcessedResponses {
    const data: { distinctId: string; response: string; personProperties?: Record<string, any> }[] = []
    let totalResponses = 0

    results?.forEach((row: SurveyResponseRow) => {
        const value = row[questionIndex] as string
        if (isEmptyOrUndefined(value)) {
            return
        }

        const response = {
            distinctId: row.at(-1) as string,
            response: value,
            personProperties: undefined as Record<string, any> | undefined,
        }

        const unparsedPersonProperties = row.at(-2)
        if (unparsedPersonProperties && unparsedPersonProperties !== null) {
            try {
                response.personProperties = JSON.parse(unparsedPersonProperties as string)
            } catch (e) {
                // Ignore parsing errors for person properties as there's no real action here
                // It just means we won't show the person properties in the question visualization
            }
        }

        totalResponses += 1
        data.push(response)
    })

    return {
        type: SurveyQuestionType.Open,
        data,
        totalResponses,
    }
}

export function processResultsForSurveyQuestions(
    questions: SurveyQuestion[],
    results: SurveyRawResults
): ResponsesByQuestion {
    const responsesByQuestion: ResponsesByQuestion = {}

    questions.forEach((question, index) => {
        // Skip questions without IDs or Link questions
        if (!question.id || question.type === SurveyQuestionType.Link) {
            return
        }

        let processedData: QuestionProcessedResponses

        switch (question.type) {
            case SurveyQuestionType.SingleChoice:
                processedData = processSingleChoiceQuestion(question, index, results)
                break
            case SurveyQuestionType.Rating:
                processedData = processRatingQuestion(question, index, results)
                break
            case SurveyQuestionType.MultipleChoice:
                processedData = processMultipleChoiceQuestion(question, index, results)
                break
            case SurveyQuestionType.Open:
                processedData = processOpenQuestion(index, results)
                break
            default:
                // Skip unknown question types
                return
        }

        responsesByQuestion[question.id] = processedData
    })

    return responsesByQuestion
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
        values: [enabledFlagLogic, ['featureFlags as enabledFlags'], surveysLogic, ['data']],
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
        setSurveyTemplateValues: (template: Partial<NewSurvey>) => ({ template }),
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
        setDateRange: (dateRange: SurveyDateRange, reloadResults: boolean = true) => ({ dateRange, reloadResults }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setFilterSurveyStatsByDistinctId: (filterByDistinctId: boolean) => ({ filterByDistinctId }),
        setBaseStatsResults: (results: SurveyBaseStatsResult) => ({ results }),
        setDismissedAndSentCount: (count: DismissedAndSentCountResult) => ({ count }),
    }),
    loaders(({ props, actions, values }) => ({
        responseSummary: {
            summarize: async ({ questionIndex, questionId }: { questionIndex?: number; questionId?: string }) => {
                return api.surveys.summarize_responses(props.id, questionIndex, questionId)
            },
        },
        survey: {
            loadSurvey: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const survey = await api.surveys.get(props.id)
                        const currentFilters = values.answerFilters
                        actions.reportSurveyViewed(survey)
                        // Initialize answer filters for all questions - first for index-based, then for id-based
                        actions.setAnswerFilters(
                            survey.questions.map((question) => {
                                const { indexBasedKey, idBasedKey } = getResponseFieldWithId(0, question.id)
                                const currentFilterForQuestion = currentFilters.find(
                                    (filter) => filter.key === idBasedKey
                                )
                                return {
                                    key: idBasedKey || indexBasedKey,
                                    operator:
                                        currentFilterForQuestion?.operator ?? DEFAULT_OPERATORS[question.type].value,
                                    type: PropertyFilterType.Event as const,
                                    value: currentFilterForQuestion?.value ?? [],
                                }
                            }),
                            false
                        )
                        actions.setDateRange(
                            {
                                date_from: getSurveyStartDateForQuery(survey),
                                date_to: getSurveyEndDateForQuery(survey),
                            },
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
                return await api.surveys.create(surveyPayload)
            },
            updateSurvey: async (surveyPayload: Partial<Survey>) => {
                const response = await api.surveys.update(props.id, surveyPayload)
                refreshTreeItem('survey', props.id)
                return response
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
                const createdSurvey = await api.surveys.create(sanitizeSurvey(payload))

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
        surveyBaseStats: {
            loadSurveyBaseStats: async (): Promise<SurveyBaseStatsResult> => {
                if (props.id === NEW_SURVEY.id || !values.survey?.start_date) {
                    return null
                }
                // if we have answer filters, we need to apply them to the query for the 'survey sent' event only
                const answerFilterCondition = values.answerFilterHogQLExpression
                    ? values.answerFilterHogQLExpression.slice(4)
                    : '1=1' // Use '1=1' for SQL TRUE

                const query = `
                    -- QUERYING BASE STATS
                    SELECT
                        event as event_name,
                        count() as total_count,
                        count(DISTINCT person_id) as unique_persons,
                        if(count() > 0, min(timestamp), null) as first_seen,
                        if(count() > 0, max(timestamp), null) as last_seen
                    FROM events
                    WHERE team_id = ${teamLogic.values.currentTeamId}
                        AND event IN ('${SurveyEventName.SHOWN}', '${SurveyEventName.DISMISSED}', '${SurveyEventName.SENT}')
                        AND properties.${SurveyEventProperties.SURVEY_ID} = '${props.id}'
                        ${values.timestampFilter}
                        AND {filters} -- Apply property filters here to the main query
                        -- Main condition for handling partial responses and answer filters:
                        AND (
                            event != '${SurveyEventName.DISMISSED}'
                            OR
                            COALESCE(JSONExtractBool(properties, '${SurveyEventProperties.SURVEY_PARTIALLY_COMPLETED}'), False) = False
                        )
                        AND (
                            -- Include non-'sent' events directly
                            event != '${SurveyEventName.SENT}'
                            OR
                            -- Include 'sent' events only if they meet the outer query's answer filter AND are in the unique list (old or latest partial/complete)
                            (
                                (${answerFilterCondition}) -- Apply answer filters ONLY to 'sent' events in the outer query
                                -- Check if the event's UUID is in the list generated by the subquery
                                ${values.partialResponsesFilter}
                            )
                        )
                    GROUP BY event` as HogQLQueryString

                const response = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
                actions.setBaseStatsResults(response.results as SurveyBaseStatsResult)
                const numberOfSurveySentEvents = response.results?.find(
                    (result) => result[0] === SurveyEventName.SENT
                )?.[1]
                actions.loadConsolidatedSurveyResults(numberOfSurveySentEvents)
                return response.results as SurveyBaseStatsResult
            },
        },
        surveyDismissedAndSentCount: {
            loadSurveyDismissedAndSentCount: async (): Promise<DismissedAndSentCountResult> => {
                if (props.id === NEW_SURVEY.id || !values.survey?.start_date) {
                    return null
                }
                // if we have answer filters, we need to apply them to the query for the 'survey sent' event only
                const answerFilterCondition =
                    values.answerFilterHogQLExpression === ''
                        ? '1=1' // Use '1=1' for SQL TRUE
                        : values.answerFilterHogQLExpression.substring(4)

                const query = `
                    -- QUERYING DISMISSED AND SENT COUNT
                    SELECT count()
                    FROM (
                        SELECT person_id
                        FROM events
                        WHERE team_id = ${teamLogic.values.currentTeamId}
                            AND event IN ('${SurveyEventName.DISMISSED}', '${SurveyEventName.SENT}')
                            AND properties.${SurveyEventProperties.SURVEY_ID} = '${props.id}'
                            ${values.timestampFilter}
                            AND (
                            event != '${SurveyEventName.DISMISSED}'
                            OR
                            COALESCE(JSONExtractBool(properties, '${SurveyEventProperties.SURVEY_PARTIALLY_COMPLETED}'), False) = False
                            )
                            AND {filters} -- Apply property filters here to reduce initial events
                        GROUP BY person_id
                        HAVING sum(if(event = '${SurveyEventName.DISMISSED}', 1, 0)) > 0 -- Has at least one dismissed event (matching property filters)
                            AND sum(if(event = '${SurveyEventName.SENT}' AND (${answerFilterCondition}), 1, 0)) > 0 -- Has at least one sent event matching BOTH property and answer filters
                    ) AS PersonsWithBothEvents` as HogQLQueryString

                const response = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters, // Property filters applied in WHERE
                        },
                    },
                })
                const count = response.results?.[0]?.[0] ?? 0
                actions.setDismissedAndSentCount(count)
                return count as DismissedAndSentCountResult
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

                const query = `
                    -- QUERYING NPS RESPONSES
                    SELECT
                        getSurveyResponse(${questionIndex}, '${question?.id}') AS survey_response,
                        COUNT(survey_response)
                    FROM events
                    WHERE event = '${SurveyEventName.SENT}'
                        AND properties.${SurveyEventProperties.SURVEY_ID} = '${props.id}'
                        ${values.timestampFilter}
                        ${values.answerFilterHogQLExpression}
                        AND {filters}
                        ${values.partialResponsesFilter}
                    GROUP BY survey_response` as HogQLQueryString

                const responseJSON = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
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

                const query = `
                    -- QUERYING NPS RECURRING RESPONSES
                    SELECT
                        JSONExtractString(properties, '${SurveyEventProperties.SURVEY_ITERATION}') AS survey_iteration,
                        getSurveyResponse(${questionIndex}, '${question?.id}') AS survey_response,
                        COUNT(survey_response)
                    FROM events
                    WHERE event = '${SurveyEventName.SENT}'
                        AND properties.${SurveyEventProperties.SURVEY_ID} = '${survey.id}'
                        ${values.timestampFilter}
                        ${values.answerFilterHogQLExpression}
                        ${values.partialResponsesFilter}
                        AND {filters}
                    GROUP BY survey_response, survey_iteration` as HogQLQueryString

                const responseJSON = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
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
                const question = values.survey.questions[questionIndex]
                const query = `
                    -- QUERYING SINGLE CHOICE RESPONSES
                    SELECT
                        getSurveyResponse(${questionIndex}, '${question?.id ? question.id : ''}') AS survey_response,
                        COUNT(survey_response)
                    FROM events
                    WHERE event = '${SurveyEventName.SENT}'
                        AND properties.${SurveyEventProperties.SURVEY_ID} = '${props.id}'
                        ${values.timestampFilter}
                        ${values.answerFilterHogQLExpression}
                        ${values.partialResponsesFilter}
                        AND survey_response != null
                        AND {filters}
                    GROUP BY survey_response` as HogQLQueryString

                const responseJSON = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
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

                // Use a WITH clause to ensure we're only counting each response once
                const query = `
                    -- QUERYING MULTIPLE CHOICE RESPONSES
                    SELECT
                        count(),
                        arrayJoin(
                            getSurveyResponse(${questionIndex}, '${question?.id ? question.id : ''}', true)
                        ) AS choice
                    FROM events
                    WHERE event == '${SurveyEventName.SENT}'
                        AND properties.${SurveyEventProperties.SURVEY_ID} == '${survey.id}'
                        ${values.timestampFilter}
                        ${values.answerFilterHogQLExpression}
                        AND {filters}
                        ${values.partialResponsesFilter}
                    GROUP BY choice
                    ORDER BY count() DESC` as HogQLQueryString

                const responseJSON = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
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

                // For open text responses, we need to check both formats in the WHERE clause
                const ids = getResponseFieldWithId(questionIndex, question?.id)

                // Build the condition to check for non-empty responses in either format
                const responseCondition = ids.idBasedKey
                    ? `(
                        (JSONHas(properties, '${ids.indexBasedKey}') AND length(trim(JSONExtractString(properties, '${ids.indexBasedKey}'))) > 0) OR
                        (JSONHas(properties, '${ids.idBasedKey}') AND length(trim(JSONExtractString(properties, '${ids.idBasedKey}'))) > 0)
                      )`
                    : `(JSONHas(properties, '${ids.indexBasedKey}') AND length(trim(JSONExtractString(properties, '${ids.indexBasedKey}'))) > 0)`

                const query = `
                    -- QUERYING OPEN TEXT RESPONSES
                    SELECT distinct_id, properties, person.properties
                    FROM events
                    WHERE event == '${SurveyEventName.SENT}'
                        AND properties.${SurveyEventProperties.SURVEY_ID} == '${survey.id}'
                        AND ${responseCondition}
                        ${values.timestampFilter}
                        ${values.answerFilterHogQLExpression}
                        AND {filters}
                        ${values.partialResponsesFilter}
                    LIMIT 20` as HogQLQueryString

                const responseJSON = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
                const { results } = responseJSON

                const events =
                    results?.map((r) => {
                        const distinct_id = r[0]
                        const properties = JSON.parse(r[1])

                        // Safely handle personProperties which might be null for non-identified users
                        let personProperties = {}
                        try {
                            if (r[2] && r[2] !== 'null') {
                                personProperties = JSON.parse(r[2])
                            }
                        } catch (e) {
                            // If parsing fails, use an empty object
                        }

                        return { distinct_id, properties, personProperties }
                    }) || []

                return { ...values.surveyOpenTextResults, [questionIndex]: { events } }
            },
        },
        consolidatedSurveyResults: {
            loadConsolidatedSurveyResults: async (
                limit = MAX_SELECT_RETURNED_ROWS
            ): Promise<ConsolidatedSurveyResults> => {
                if (props.id === NEW_SURVEY.id || !values.survey?.start_date) {
                    return { responsesByQuestion: {} }
                }

                // Build an array of all questions with their types
                const questionFields = values.survey.questions.map((question, index) => {
                    return `${getSurveyResponse(question, index)} AS q${index}_response`
                })

                // Also get distinct_id and person properties for open text questions
                const query = `
                    -- QUERYING ALL SURVEY RESPONSES IN ONE GO
                    SELECT
                        ${questionFields.join(',\n')},
                        person.properties,
                        events.distinct_id
                    FROM events
                    WHERE event = '${SurveyEventName.SENT}'
                        AND properties.${SurveyEventProperties.SURVEY_ID} = '${props.id}'
                        ${values.timestampFilter}
                        ${values.answerFilterHogQLExpression}
                        ${values.partialResponsesFilter}
                        AND {filters}
                    ORDER BY events.timestamp DESC
                    LIMIT ${limit}` as HogQLQueryString

                const responseJSON = await api.queryHogQL(query, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
                const { results } = responseJSON

                // Process the results into a format that can be used by each question type
                const responsesByQuestion = processResultsForSurveyQuestions(values.survey.questions, results)

                return { responsesByQuestion }
            },
        },
    })),
    listeners(({ actions, values }) => {
        const reloadAllSurveyResults = debounce((): void => {
            // Load survey stats data
            actions.loadSurveyBaseStats()
            actions.loadSurveyDismissedAndSentCount()

            // No need to reload the other results if the new question viz is enabled, as they are not used
            // So we early return here, as the consolidated survey results are queried in the surveyBaseStats loader
            if (values.isNewQuestionVizEnabled) {
                return
            }

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
                // Trigger stats loading after survey loads
                if (values.survey.id !== NEW_SURVEY.id && values.survey.start_date) {
                    actions.loadSurveyBaseStats()
                    actions.loadSurveyDismissedAndSentCount()
                }

                if (values.survey.start_date) {
                    activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.LaunchSurvey)
                }
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
            setDateRange: ({ reloadResults }) => {
                if (reloadResults) {
                    reloadAllSurveyResults()
                }
            },
        }
    }),
    reducers({
        filterSurveyStatsByDistinctId: [
            true,
            { persist: true },
            {
                setFilterSurveyStatsByDistinctId: (_, { filterByDistinctId }) => filterByDistinctId,
            },
        ],
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
            { persist: true },
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

                    // Validate response-based branching is only used with compatible question types
                    if (
                        type === SurveyQuestionBranchingType.ResponseBased &&
                        !canQuestionHaveResponseBasedBranching(question)
                    ) {
                        question.branching = undefined
                        lemonToast.error(
                            <>
                                Response-based branching is not supported for {question.type} questions. Removing
                                branching logic from this question.
                            </>
                        )
                    } else {
                        // Use centralized branching config creation
                        question.branching = createBranchingConfig(type, specificQuestionIndex)
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

                    // Use centralized validation for response-based branching compatibility
                    if (!canQuestionHaveResponseBasedBranching(question)) {
                        throw new Error(
                            `Survey question type must be ${SurveyQuestionType.Rating} or ${SurveyQuestionType.SingleChoice} for response-based branching`
                        )
                    }

                    if (question.branching?.type !== SurveyQuestionBranchingType.ResponseBased) {
                        throw new Error(
                            `Survey question branching type must be ${SurveyQuestionBranchingType.ResponseBased}`
                        )
                    }

                    if ('responseValues' in question.branching) {
                        if (nextStep === SurveyQuestionBranchingType.NextQuestion) {
                            // Remove the response mapping to default to next question
                            delete question.branching.responseValues[responseValue]
                        } else if (nextStep === SurveyQuestionBranchingType.End) {
                            // Map response to end survey
                            question.branching.responseValues[responseValue] = SurveyQuestionBranchingType.End
                        } else if (nextStep === SurveyQuestionBranchingType.SpecificQuestion) {
                            // Map response to specific question index
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
            { persist: true },
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
            { compare: true } as CompareFilter,
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
            },
        ],
        surveyBaseStatsInternal: [
            null as SurveyBaseStatsResult,
            {
                setBaseStatsResults: (_, { results }) => results,
                loadSurveySuccess: () => null,
                resetSurvey: () => null,
            },
        ],
        surveyDismissedAndSentCountInternal: [
            null as DismissedAndSentCountResult,
            {
                setDismissedAndSentCount: (_, { count }) => count,
                loadSurveySuccess: () => null,
                resetSurvey: () => null,
            },
        ],
    }),
    selectors({
        isPartialResponsesEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.SURVEYS_PARTIAL_RESPONSES]
            },
        ],
        isNewQuestionVizEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.SURVEYS_NEW_QUESTION_VIZ]
            },
        ],
        timestampFilter: [
            (s) => [s.survey, s.dateRange],
            (survey: Survey, dateRange: SurveyDateRange): string => {
                // If no date range provided, use the survey's default date range
                if (!dateRange) {
                    return `AND timestamp >= '${getSurveyStartDateForQuery(survey)}'
                AND timestamp <= '${getSurveyEndDateForQuery(survey)}'`
                }

                // ----- Handle FROM date -----
                // Parse the date string to a dayjs object
                let fromDateDayjs = dateStringToDayJs(dateRange.date_from)

                // Use survey creation date as lower bound if needed
                const surveyStartDayjs = dayjs(getSurveyStartDateForQuery(survey))
                if (surveyStartDayjs && fromDateDayjs && fromDateDayjs.isBefore(surveyStartDayjs)) {
                    fromDateDayjs = surveyStartDayjs
                }

                // Fall back to survey start date if no valid from date
                const fromDate = fromDateDayjs
                    ? fromDateDayjs.utc().format(DATE_FORMAT)
                    : getSurveyStartDateForQuery(survey)

                // ----- Handle TO date -----
                // Parse the date string or use current time
                const toDateDayjs = dateStringToDayJs(dateRange.date_to) || dayjs()

                // Use survey end date as upper bound if it exists
                const toDate = survey.end_date
                    ? getSurveyEndDateForQuery(survey)
                    : toDateDayjs.utc().format(DATE_FORMAT)

                return `AND timestamp >= '${fromDate}'
                AND timestamp <= '${toDate}'`
            },
        ],
        partialResponsesFilter: [
            (s) => [s.isPartialResponsesEnabled, s.survey],
            (isPartialResponsesEnabled: boolean, survey: Survey): string => {
                if (isPartialResponsesEnabled && survey.enable_partial_responses) {
                    return buildPartialResponsesFilter(survey)
                }
                /**
                 * Return only complete responses. For pre-partial responses, we didn't have the survey_completed property.
                 * So we return all responses that don't have it.
                 * For posthog-js > 1.240, we use the $survey_completed property.
                 */
                return `AND (
                            NOT JSONHas(properties, '${SurveyEventProperties.SURVEY_COMPLETED}')
                            OR JSONExtractBool(properties, '${SurveyEventProperties.SURVEY_COMPLETED}') = true
                        )`
            },
        ],
        isAdaptiveLimitFFEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.SURVEYS_ADAPTIVE_LIMITS]
            },
        ],
        isAnyResultsLoading: [
            (s) => [
                s.surveyBaseStatsLoading,
                s.surveyDismissedAndSentCountLoading,
                s.surveyRatingResultsReady,
                s.surveySingleChoiceResultsReady,
                s.surveyMultipleChoiceResultsReady,
                s.surveyOpenTextResultsReady,
                s.surveyRecurringNPSResultsReady,
                s.consolidatedSurveyResultsLoading,
                s.isNewQuestionVizEnabled,
            ],
            (
                surveyBaseStatsLoading: boolean,
                surveyDismissedAndSentCountLoading: boolean,
                surveyRatingResultsReady: boolean,
                surveySingleChoiceResultsReady: boolean,
                surveyMultipleChoiceResultsReady: boolean,
                surveyOpenTextResultsReady: boolean,
                surveyRecurringNPSResultsReady: boolean,
                consolidatedSurveyResultsLoading: boolean,
                isNewQuestionVizEnabled: boolean
            ) => {
                if (isNewQuestionVizEnabled) {
                    return (
                        consolidatedSurveyResultsLoading || surveyBaseStatsLoading || surveyDismissedAndSentCountLoading
                    )
                }

                return (
                    surveyBaseStatsLoading ||
                    surveyDismissedAndSentCountLoading ||
                    !surveyRatingResultsReady ||
                    !surveySingleChoiceResultsReady ||
                    !surveyMultipleChoiceResultsReady ||
                    !surveyOpenTextResultsReady ||
                    !surveyRecurringNPSResultsReady
                )
            },
        ],
        defaultAnswerFilters: [
            (s) => [s.survey],
            (survey: Survey): EventPropertyFilter[] => {
                return survey.questions.map((question) => {
                    const { indexBasedKey, idBasedKey } = getResponseFieldWithId(0, question.id)
                    return {
                        key: idBasedKey || indexBasedKey,
                        operator: DEFAULT_OPERATORS[question.type].value,
                        type: PropertyFilterType.Event as const,
                        value: [],
                    }
                })
            },
        ],
        isSurveyRunning: [
            (s) => [s.survey],
            (survey: Survey): boolean => {
                return isSurveyRunning(survey)
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
        projectTreeRef: [
            () => [(_, props: SurveyLogicProps) => props.id],
            (id): ProjectTreeRef => {
                return { type: 'survey', ref: id === 'new' ? null : String(id) }
            },
        ],
        answerFilterHogQLExpression: [
            (s) => [s.survey, s.answerFilters],
            (survey: Survey, answerFilters: EventPropertyFilter[]): string => {
                return createAnswerFilterHogQLExpression(answerFilters, survey)
            },
        ],
        dataTableQuery: [
            (s) => [s.survey, s.propertyFilters, s.answerFilterHogQLExpression, s.partialResponsesFilter, s.dateRange],
            (
                survey: Survey,
                propertyFilters: AnyPropertyFilter[],
                answerFilterHogQLExpression: string,
                partialResponsesFilter: string,
                dateRange: SurveyDateRange
            ): DataTableNode | null => {
                if (survey.id === 'new') {
                    return null
                }
                const startDate = getSurveyStartDateForQuery(survey)
                const endDate = getSurveyEndDateForQuery(survey)

                const where = [`event == '${SurveyEventName.SENT}'`, partialResponsesFilter.replace(/^AND\s+/, '')]

                if (answerFilterHogQLExpression !== '') {
                    // skip the 'AND ' prefix
                    where.push(answerFilterHogQLExpression.substring(4))
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: [
                            '*',
                            ...survey.questions.map((q, i) => {
                                if (q.type === SurveyQuestionType.MultipleChoice) {
                                    return `arrayStringConcat(${getSurveyResponse(q, i)}, ', ') -- ${q.question}`
                                }
                                // Use the new condition that checks both formats
                                return `${getSurveyResponse(q, i)} -- ${q.question}`
                            }),
                            'timestamp',
                            'person',
                            `coalesce(JSONExtractString(properties, '$lib_version')) -- Library Version`,
                            `coalesce(JSONExtractString(properties, '$lib')) -- Library`,
                            `coalesce(JSONExtractString(properties, '$current_url')) -- URL`,
                        ],
                        orderBy: ['timestamp DESC'],
                        where,
                        after: dateRange?.date_from || startDate,
                        before: dateRange?.date_to || endDate,
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: SurveyEventProperties.SURVEY_ID,
                                operator: PropertyOperator.Exact,
                                value: survey.id,
                            },
                            ...propertyFilters,
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

                    return npsBreakdown.score
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
                const questionResults = surveyRatingResults[questionIdx]
                if (!questionResults) {
                    return null
                }

                return calculateNpsBreakdown(questionResults)
            },
        ],
        getBranchingDropdownValue: [
            (s) => [s.survey],
            (survey) => (questionIndex: number, question: SurveyQuestion) => {
                if (question.branching?.type) {
                    const { type } = question.branching

                    if (type === SurveyQuestionBranchingType.SpecificQuestion) {
                        const nextQuestionIndex = question.branching.index
                        return branchingConfigToDropdownValue(type, nextQuestionIndex)
                    }

                    return type
                }

                // No branching specified, default to Next question / Confirmation message
                return getDefaultBranchingType(questionIndex, survey.questions.length)
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
                                key: SurveyEventProperties.SURVEY_ID,
                                value: survey.id,
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                event: SurveyEventName.SENT,
                                name: SurveyEventName.SENT,
                                math: BaseMathType.TotalCount,
                            },
                            {
                                kind: NodeKind.EventsNode,
                                event: SurveyEventName.SHOWN,
                                name: SurveyEventName.SHOWN,
                                math: BaseMathType.TotalCount,
                            },
                            {
                                kind: NodeKind.EventsNode,
                                event: SurveyEventName.DISMISSED,
                                name: SurveyEventName.DISMISSED,
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
        processedSurveyStats: [
            (s) => [s.surveyBaseStatsInternal, s.surveyDismissedAndSentCountInternal],
            (
                baseStatsResults: SurveyBaseStatsResult,
                dismissedAndSentCount: DismissedAndSentCountResult
            ): SurveyStats | null => {
                if (!baseStatsResults) {
                    return null
                }

                const defaultEventStats: Omit<SurveyEventStats, 'first_seen' | 'last_seen'> = {
                    total_count: 0,
                    unique_persons: 0,
                    unique_persons_only_seen: 0,
                    total_count_only_seen: 0,
                }

                const stats: SurveyStats = {
                    [SurveyEventName.SHOWN]: { ...defaultEventStats, first_seen: null, last_seen: null },
                    [SurveyEventName.DISMISSED]: { ...defaultEventStats, first_seen: null, last_seen: null },
                    [SurveyEventName.SENT]: { ...defaultEventStats, first_seen: null, last_seen: null },
                }

                // Process base results
                baseStatsResults.forEach(([eventName, totalCount, uniquePersons, firstSeen, lastSeen]) => {
                    const eventStats: SurveyEventStats = {
                        total_count: totalCount,
                        unique_persons: uniquePersons,
                        first_seen: firstSeen ? dayjs(firstSeen).toISOString() : null,
                        last_seen: lastSeen ? dayjs(lastSeen).toISOString() : null,
                        unique_persons_only_seen: 0,
                        total_count_only_seen: 0,
                    }
                    if (eventName === SurveyEventName.SHOWN) {
                        stats[SurveyEventName.SHOWN] = eventStats
                    } else if (eventName === SurveyEventName.DISMISSED) {
                        stats[SurveyEventName.DISMISSED] = eventStats
                    } else if (eventName === SurveyEventName.SENT) {
                        stats[SurveyEventName.SENT] = eventStats
                    }
                })

                // Adjust dismissed unique count
                const adjustedDismissedUnique = Math.max(
                    0,
                    stats[SurveyEventName.DISMISSED].unique_persons - (dismissedAndSentCount ?? 0)
                )
                stats[SurveyEventName.DISMISSED].unique_persons = adjustedDismissedUnique

                // Calculate derived 'only_seen' counts
                const uniqueShown = stats[SurveyEventName.SHOWN].unique_persons
                const uniqueDismissed = stats[SurveyEventName.DISMISSED].unique_persons
                const uniqueSent = stats[SurveyEventName.SENT].unique_persons

                const totalShown = stats[SurveyEventName.SHOWN].total_count
                const totalDismissed = stats[SurveyEventName.DISMISSED].total_count
                const totalSent = stats[SurveyEventName.SENT].total_count

                stats[SurveyEventName.SHOWN].unique_persons_only_seen = Math.max(
                    0,
                    uniqueShown - uniqueDismissed - uniqueSent
                )
                stats[SurveyEventName.SHOWN].total_count_only_seen = Math.max(
                    0,
                    totalShown - totalDismissed - totalSent
                )

                return stats
            },
        ],
        surveyRates: [
            (s) => [s.processedSurveyStats],
            (stats: SurveyStats | null): SurveyRates => {
                const defaultRates: SurveyRates = {
                    response_rate: 0.0,
                    dismissal_rate: 0.0,
                    unique_users_response_rate: 0.0,
                    unique_users_dismissal_rate: 0.0,
                }

                if (!stats) {
                    return defaultRates
                }

                const shownCount = stats[SurveyEventName.SHOWN].total_count
                if (shownCount > 0) {
                    const sentCount = stats[SurveyEventName.SENT].total_count
                    const dismissedCount = stats[SurveyEventName.DISMISSED].total_count
                    const uniqueUsersShownCount = stats[SurveyEventName.SHOWN].unique_persons
                    const uniqueUsersSentCount = stats[SurveyEventName.SENT].unique_persons
                    const uniqueUsersDismissedCount = stats[SurveyEventName.DISMISSED].unique_persons

                    return {
                        response_rate: parseFloat(((sentCount / shownCount) * 100).toFixed(2)),
                        dismissal_rate: parseFloat(((dismissedCount / shownCount) * 100).toFixed(2)),
                        unique_users_response_rate: parseFloat(
                            ((uniqueUsersSentCount / uniqueUsersShownCount) * 100).toFixed(2)
                        ),
                        unique_users_dismissal_rate: parseFloat(
                            ((uniqueUsersDismissedCount / uniqueUsersShownCount) * 100).toFixed(2)
                        ),
                    }
                }
                return defaultRates
            },
        ],
    }),
    forms(({ actions, props, values }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name, questions, appearance, type }) => {
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
                    appearance:
                        sanitizedAppearance &&
                        validateSurveyAppearance(
                            sanitizedAppearance,
                            questions.some((q) => q.type === SurveyQuestionType.Rating),
                            type
                        ),
                }
            },
            submit: (surveyPayload) => {
                if (values.hasCycle) {
                    actions.reportSurveyCycleDetected(values.survey)

                    return lemonToast.error(
                        'Your survey contains an endless cycle. Please revisit your branching rules.'
                    )
                }

                const payload = sanitizeSurvey(surveyPayload)

                // when the survey is being submitted, we should turn off editing mode
                actions.editingSurvey(false)
                if (props.id && props.id !== 'new') {
                    actions.updateSurvey(payload)
                } else {
                    openSaveToModal({
                        defaultFolder: 'Unfiled/Surveys',
                        callback: (folder) =>
                            actions.createSurvey(
                                typeof folder === 'string'
                                    ? {
                                          ...payload,
                                          _create_in_folder: folder,
                                      }
                                    : payload
                            ),
                    })
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
