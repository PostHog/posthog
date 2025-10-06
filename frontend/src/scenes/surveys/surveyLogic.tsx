import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS, PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { FeatureFlagsSet, featureFlagLogic as enabledFlagLogic } from 'lib/logic/featureFlagLogic'
import { allOperatorsMapping, debounce, hasFormErrors, isObject } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { Scene } from 'scenes/sceneTypes'
import {
    branchingConfigToDropdownValue,
    canQuestionHaveResponseBasedBranching,
    createBranchingConfig,
    getDefaultBranchingType,
} from 'scenes/surveys/components/question-branching/utils'
import { getDemoDataForSurvey } from 'scenes/surveys/utils/demoDataGenerator'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ActivationTask, activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { MAX_SELECT_RETURNED_ROWS } from '~/queries/nodes/DataTable/DataTableExport'
import { CompareFilter, DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { SurveyAnalysisQuestionGroup, SurveyAnalysisResponseItem } from '~/queries/schema/schema-surveys'
import { HogQLQueryString } from '~/queries/utils'
import {
    ActivityScope,
    AnyPropertyFilter,
    BaseMathType,
    Breadcrumb,
    ChoiceQuestionProcessedResponses,
    ChoiceQuestionResponseData,
    ConsolidatedSurveyResults,
    EventPropertyFilter,
    FeatureFlagFilters,
    IntervalType,
    MultipleSurveyQuestion,
    OpenQuestionProcessedResponses,
    OpenQuestionResponseData,
    ProductKey,
    ProjectTreeRef,
    PropertyFilterType,
    PropertyOperator,
    QuestionProcessedResponses,
    RatingSurveyQuestion,
    ResponsesByQuestion,
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
    SurveyRawResults,
    SurveyResponseRow,
    SurveySchedule,
    SurveyStats,
} from '~/types'

import {
    NEW_SURVEY,
    NewSurvey,
    SURVEY_CREATED_SOURCE,
    SURVEY_RATING_SCALE,
    defaultSurveyAppearance,
    defaultSurveyFieldValues,
} from './constants'
import type { surveyLogicType } from './surveyLogicType'
import { surveysLogic } from './surveysLogic'
import {
    DATE_FORMAT,
    buildPartialResponsesFilter,
    buildSurveyTimestampFilter,
    calculateSurveyRates,
    createAnswerFilterHogQLExpression,
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

export type SurveyDemoData = ReturnType<typeof getDemoDataForSurvey>

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
        name: `${survey.name} (duplicated at ${dayjs().format('YYYY-MM-DD HH:mm:ss')})`,
        archived: false,
        start_date: null,
        end_date: null,
        targeting_flag_filters: survey.targeting_flag?.filters ?? NEW_SURVEY.targeting_flag_filters,
        linked_flag_id: survey.linked_flag?.id ?? NEW_SURVEY.linked_flag_id,
    }
}

function isEmptyOrUndefined(value: any): boolean {
    return value === null || value === undefined || value === ''
}

function isQuestionOpenChoice(question: SurveyQuestion, choiceIndex: number): boolean {
    if (question.type !== SurveyQuestionType.SingleChoice && question.type !== SurveyQuestionType.MultipleChoice) {
        return false
    }
    return !!(choiceIndex === question.choices.length - 1 && question?.hasOpenChoice)
}

// Helper to extract person data from a survey response row
function extractPersonData(row: SurveyResponseRow): {
    distinctId: string
    personProperties?: Record<string, any>
    timestamp: string
} {
    const distinctId = row.at(-2) as string
    const timestamp = row.at(-1) as string
    // now, we're querying for all PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES, starting from the third last value, so build our person properties object
    // from those values. We use them to have a display name for the person
    const personProperties: Record<string, any> = {}
    const personDisplayProperties = PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    let hasAnyProperties = false
    for (let i = 0; i < personDisplayProperties.length; i++) {
        const value = row.at(-3 - i) as string
        if (value && value !== null && value !== '') {
            personProperties[personDisplayProperties[i]] = value
            hasAnyProperties = true
        }
    }
    return { distinctId, personProperties: hasAnyProperties ? personProperties : undefined, timestamp }
}

// Helper to count a choice and store person data for latest occurrence
function countChoice(
    choice: string,
    counts: { [key: string]: number },
    latestResponsePersonData: { [key: string]: ReturnType<typeof extractPersonData> },
    personData: ReturnType<typeof extractPersonData>
): void {
    if (isEmptyOrUndefined(choice)) {
        return
    }

    counts[choice] = (counts[choice] || 0) + 1

    // Always store the latest person data - this gives us the most recent respondent
    // for each choice to display in the UI (e.g., "Sarah was the last to pick this option")
    latestResponsePersonData[choice] = personData
}

// Shared utility for processing choice-based questions
function processChoiceQuestion(
    question: MultipleSurveyQuestion,
    questionIndex: number,
    results: SurveyRawResults,
    questionType: SurveyQuestionType.SingleChoice | SurveyQuestionType.MultipleChoice
): ChoiceQuestionProcessedResponses {
    const counts: { [key: string]: number } = {}
    // Store person data for the most recent person who selected each choice - used in UI to show
    // "who last picked this option" with avatar/name when hovering over choice visualizations
    const latestResponsePersonData: { [key: string]: ReturnType<typeof extractPersonData> } = {}
    let total = 0

    // Zero-fill predefined choices (excluding open choice)
    question.choices?.forEach((choice: string, choiceIndex: number) => {
        if (!isQuestionOpenChoice(question, choiceIndex)) {
            counts[choice] = 0
        }
    })

    // Process each response
    results?.forEach((row: SurveyResponseRow) => {
        const rawValue = row[questionIndex]
        if (rawValue === null || rawValue === undefined) {
            return
        }

        const personData = extractPersonData(row)

        if (questionType === SurveyQuestionType.SingleChoice) {
            const value = rawValue as string
            if (!isEmptyOrUndefined(value)) {
                countChoice(value, counts, latestResponsePersonData, personData)
                total += 1
            }
        } else {
            // Multiple choice
            const choices = rawValue as string[]

            if (choices.length > 0) {
                total += 1
                choices.forEach((choice) => {
                    const cleaned = choice.replace(/^['"]+|['"]+$/g, '')
                    countChoice(cleaned, counts, latestResponsePersonData, personData)
                })
            }
        }
    })

    const data = Object.entries(counts)
        .map(([label, value]) => {
            const baseData = {
                label,
                value,
                isPredefined: question.choices?.includes(label) ?? false,
            }

            // Attach the latest person's data who selected this choice (for UI display)
            if (latestResponsePersonData[label]) {
                return {
                    ...baseData,
                    distinctId: latestResponsePersonData[label].distinctId,
                    personProperties: latestResponsePersonData[label].personProperties,
                    timestamp: latestResponsePersonData[label].timestamp,
                }
            }

            return baseData
        })
        .sort((a, b) => b.value - a.value)

    return {
        type: questionType,
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

function processOpenQuestion(questionIndex: number, results: SurveyRawResults): OpenQuestionProcessedResponses {
    const data: { distinctId: string; response: string; personProperties?: Record<string, any>; timestamp?: string }[] =
        []
    let totalResponses = 0

    results?.forEach((row: SurveyResponseRow) => {
        const value = row[questionIndex] as string
        if (isEmptyOrUndefined(value)) {
            return
        }

        const personData = extractPersonData(row)
        const response = {
            distinctId: personData.distinctId,
            response: value,
            personProperties: personData.personProperties,
            timestamp: personData.timestamp,
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
            case SurveyQuestionType.MultipleChoice:
                processedData = processChoiceQuestion(question, index, results, question.type)
                break
            case SurveyQuestionType.Rating:
                processedData = processRatingQuestion(question, index, results)
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
            teamLogic,
            ['addProductIntent'],
        ],
        values: [
            enabledFlagLogic,
            ['featureFlags as enabledFlags'],
            surveysLogic,
            ['data'],
            userLogic,
            ['user'],
            teamLogic,
            ['currentTeam'],
            propertyDefinitionsModel,
            ['propertyDefinitionsByType'],
        ],
    })),
    actions({
        setSurveyMissing: true,
        editingSurvey: (editing: boolean) => ({ editing }),
        setDefaultForQuestionType: (idx: number, surveyQuestion: SurveyQuestion, type: SurveyQuestionType) => ({
            idx,
            surveyQuestion,
            type,
        }),
        setQuestionBranchingType: (questionIndex, type, specificQuestionIndex) => ({
            questionIndex,
            type,
            specificQuestionIndex,
        }),
        setMultipleSurveyQuestion: (
            questionIndex: number,
            question: MultipleSurveyQuestion,
            type: SurveyQuestionType.MultipleChoice | SurveyQuestionType.SingleChoice
        ) => ({
            questionIndex,
            question,
            type,
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
        setIsDuplicateToProjectModalOpen: (isOpen: boolean) => ({ isOpen }),
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
                        actions.addProductIntent({
                            product_type: ProductKey.SURVEYS,
                            intent_context: ProductIntentContext.SURVEY_VIEWED,
                            metadata: {
                                survey_id: survey.id,
                            },
                        })
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
                const response = await api.surveys.create(surveyPayload)
                actions.addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_CREATED,
                    metadata: {
                        survey_id: response.id,
                        source: SURVEY_CREATED_SOURCE.SURVEY_FORM,
                    },
                })
                return response
            },
            updateSurvey: async (surveyPayload: Partial<Survey> & { intentContext?: ProductIntentContext }) => {
                const response = await api.surveys.update(props.id, surveyPayload)
                if (surveyPayload.intentContext) {
                    actions.addProductIntent({
                        product_type: ProductKey.SURVEYS,
                        intent_context: surveyPayload.intentContext,
                        metadata: {
                            survey_id: values.survey.id,
                        },
                    })
                }
                refreshTreeItem('survey', props.id)
                return response
            },
            launchSurvey: async () => {
                const startDate = dayjs()
                const response = await api.surveys.update(props.id, { start_date: startDate.toISOString() })
                actions.addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_LAUNCHED,
                    metadata: {
                        survey_id: response.id,
                    },
                })
                return response
            },
            stopSurvey: async () => {
                const response = await api.surveys.update(props.id, { end_date: dayjs().toISOString() })
                actions.addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_COMPLETED,
                    metadata: {
                        survey_id: response.id,
                    },
                })
                return response
            },
            resumeSurvey: async () => {
                const response = await api.surveys.update(props.id, { end_date: null })
                actions.addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_RESUMED,
                    metadata: {
                        survey_id: response.id,
                    },
                })
                return response
            },
        },
        duplicatedSurvey: {
            duplicateSurvey: async () => {
                const { survey } = values
                const payload = duplicateExistingSurvey(survey)
                try {
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

                    actions.setIsDuplicateToProjectModalOpen(false)
                    actions.reportSurveyCreated(createdSurvey, true)
                    actions.addProductIntent({
                        product_type: ProductKey.SURVEYS,
                        intent_context: ProductIntentContext.SURVEY_DUPLICATED,
                        metadata: {
                            survey_id: createdSurvey.id,
                        },
                    })
                    return survey
                } catch (error) {
                    posthog.captureException(error, {
                        action: 'duplicate-survey',
                        survey: payload,
                    })
                    lemonToast.error('Error while duplicating survey. Please try again.')
                    return null
                }
            },
        },
        duplicatedToProjectSurvey: {
            duplicateToProject: async ({ sourceSurvey, targetTeamId }) => {
                const payload = duplicateExistingSurvey(sourceSurvey)
                const createdSurvey = await api.surveys.create(sanitizeSurvey(payload), targetTeamId)

                lemonToast.success('Survey duplicated to another project.', {
                    toastId: `survey-duplicated-to-project-${createdSurvey.id}`,
                    button: {
                        label: 'View Survey',
                        action: () => {
                            window.open(`${window.location.origin}/project/${targetTeamId}/surveys/${createdSurvey.id}`)
                        },
                    },
                })

                actions.reportSurveyCreated(createdSurvey, true)
                actions.setIsDuplicateToProjectModalOpen(false)
                actions.addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_DUPLICATED,
                    metadata: {
                        survey_id: createdSurvey.id,
                    },
                })
                return sourceSurvey
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

                // Also get distinct_id, person properties, and timestamp for open text questions
                const query = `
                    -- QUERYING ALL SURVEY RESPONSES IN ONE GO
                    SELECT
                        ${questionFields.join(',\n')},
                        ${PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES.map((property) => `person.properties.${property}`).join(',\n')},
                        events.distinct_id,
                        events.timestamp
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
                actions.addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_ARCHIVED,
                    metadata: {
                        survey_id: values.survey.id,
                    },
                })
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
        isDuplicateToProjectModalOpen: [
            false,
            {
                setIsDuplicateToProjectModalOpen: (_, { isOpen }) => isOpen,
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
                setDefaultForQuestionType: (state, { idx, type, surveyQuestion }) => {
                    const question =
                        defaultSurveyFieldValues[surveyQuestion.type].questions[0].question !== surveyQuestion.question
                            ? surveyQuestion.question
                            : defaultSurveyFieldValues[type].questions[0].question
                    const description =
                        defaultSurveyFieldValues[surveyQuestion.type].questions[0].description !==
                        surveyQuestion.description
                            ? surveyQuestion.description
                            : defaultSurveyFieldValues[type].questions[0].description
                    const thankYouMessageHeader =
                        defaultSurveyFieldValues[surveyQuestion.type].appearance.thankYouMessageHeader !==
                        state.appearance?.thankYouMessageHeader
                            ? state.appearance?.thankYouMessageHeader
                            : defaultSurveyFieldValues[type].appearance.thankYouMessageHeader
                    const newQuestions = [...state.questions]

                    const q = {
                        ...surveyQuestion,
                    }
                    if (q.type === SurveyQuestionType.MultipleChoice || q.type === SurveyQuestionType.SingleChoice) {
                        delete q.hasOpenChoice
                    }
                    newQuestions[idx] = {
                        ...q,
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
                setMultipleSurveyQuestion: (state, { questionIndex, question, type }) => {
                    const newQuestions = [...state.questions]
                    const newQuestion: MultipleSurveyQuestion = {
                        ...question,
                        type,
                    }
                    newQuestions[questionIndex] = newQuestion
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
        timestampFilter: [
            (s) => [s.survey, s.dateRange],
            (survey: Survey, dateRange: SurveyDateRange): string => {
                return buildSurveyTimestampFilter(survey, dateRange)
            },
        ],
        partialResponsesFilter: [
            (s) => [s.survey],
            (survey: Survey): string => {
                if (survey.enable_partial_responses) {
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
        isSurveyAnalysisMaxToolEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.SURVEY_ANALYSIS_MAX_TOOL]
            },
        ],
        isExternalSurveyFFEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.EXTERNAL_SURVEYS]
            },
        ],
        isAdaptiveLimitFFEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.SURVEYS_ADAPTIVE_LIMITS]
            },
        ],
        isAnyResultsLoading: [
            (s) => [s.surveyBaseStatsLoading, s.surveyDismissedAndSentCountLoading, s.consolidatedSurveyResultsLoading],
            (
                surveyBaseStatsLoading: boolean,
                surveyDismissedAndSentCountLoading: boolean,
                consolidatedSurveyResultsLoading: boolean
            ) => {
                return consolidatedSurveyResultsLoading || surveyBaseStatsLoading || surveyDismissedAndSentCountLoading
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
                    iconType: 'survey',
                },
                {
                    key: [Scene.Survey, survey?.id || 'new'],
                    name: survey.name,
                    iconType: 'survey',
                },
            ],
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.survey],
            (survey: Survey): SidePanelSceneContext | null => {
                return survey?.id && survey.id !== 'new'
                    ? {
                          activity_scope: ActivityScope.SURVEY,
                          activity_item_id: `${survey.id}`,
                      }
                    : null
            },
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
                const start = dayjs(survey.created_at).utc().startOf('day').format(DATE_FORMAT)
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
            (processedSurveyStats: SurveyStats | null): SurveyRates | null => {
                return calculateSurveyRates(processedSurveyStats)
            },
        ],
        surveyDemoData: [
            (s) => [s.survey],
            (survey: Survey | NewSurvey): SurveyDemoData => {
                return getDemoDataForSurvey(survey)
            },
        ],
        formattedOpenEndedResponses: [
            (s) => [s.consolidatedSurveyResults, s.survey],
            (
                consolidatedResults: ConsolidatedSurveyResults,
                survey: Survey | NewSurvey
            ): SurveyAnalysisQuestionGroup[] => {
                if (!consolidatedResults?.responsesByQuestion || !survey.questions) {
                    return []
                }

                // Helper function to extract response info
                const extractResponseInfo = (
                    response: OpenQuestionResponseData | ChoiceQuestionResponseData
                ): { timestamp: string } => ({
                    timestamp: response.timestamp ?? '',
                })

                const responsesByQuestion: SurveyAnalysisQuestionGroup[] = []

                Object.entries(consolidatedResults.responsesByQuestion).forEach(([questionId, processedData]) => {
                    const question = survey.questions.find((q) => q.id === questionId)
                    if (!question) {
                        return
                    }

                    const questionResponses: SurveyAnalysisResponseItem[] = []

                    if (processedData.type === SurveyQuestionType.Open) {
                        // Pure open questions
                        const openData = processedData as OpenQuestionProcessedResponses

                        openData.data.forEach((response) => {
                            if (response.response?.trim()) {
                                const responseInfo = extractResponseInfo(response)
                                questionResponses.push({
                                    responseText: response.response.trim(),
                                    ...responseInfo,
                                    isOpenEnded: true,
                                })
                            }
                        })
                    } else if (
                        processedData.type === SurveyQuestionType.SingleChoice ||
                        processedData.type === SurveyQuestionType.MultipleChoice
                    ) {
                        // Choice questions with open input (isPredefined = false)
                        const choiceData = processedData as ChoiceQuestionProcessedResponses

                        choiceData.data.forEach((item) => {
                            if (!item.isPredefined && item.label?.trim()) {
                                const responseInfo = extractResponseInfo(item)
                                questionResponses.push({
                                    responseText: item.label.trim(),
                                    ...responseInfo,
                                    isOpenEnded: true,
                                })
                            }
                        })
                    }

                    // Only add question if it has open-ended responses
                    if (questionResponses.length > 0) {
                        responsesByQuestion.push({
                            questionName: question.question,
                            questionId,
                            responses: questionResponses,
                        })
                    }
                })

                return responsesByQuestion
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
                    actions.addProductIntent({
                        product_type: ProductKey.SURVEYS,
                        intent_context: ProductIntentContext.SURVEY_EDITED,
                        metadata: {
                            survey_id: values.survey.id,
                        },
                    })
                } else {
                    actions.createSurvey({ ...payload, _create_in_folder: 'Unfiled/Surveys' })
                }
            },
        },
    })),
    urlToAction(({ actions, props, values }) => ({
        [urls.survey(props.id ?? 'new')]: (_, { edit }, { fromTemplate }, { method }) => {
            // We always set the editingSurvey to true when we create a new survey
            if (props.id === 'new') {
                actions.editingSurvey(true)
            }
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                // When pushing to `/new` and the id matches the new survey's id, do not load the survey again
                if (props.id === 'new' && values.survey.id === NEW_SURVEY.id && !fromTemplate) {
                    return
                }
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
