import { actions, afterMount, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { FeatureFlagsSet, featureFlagLogic as enabledFlagLogic } from 'lib/logic/featureFlagLogic'
import { allOperatorsMapping, hasFormErrors, isObject, objectClean } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
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

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    CompareFilter,
    DataTableNode,
    InsightVizNode,
    NodeKind,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'
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
    HogFunctionType,
    IntervalType,
    MultipleSurveyQuestion,
    OpenQuestionProcessedResponses,
    OpenQuestionResponseData,
    ProjectTreeRef,
    PropertyFilterType,
    PropertyOperator,
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
    SurveySchedule,
    SurveyStats,
} from '~/types'

import {
    LOADING_SURVEY_RESULTS_TOAST_ID,
    NEW_SURVEY,
    NewSurvey,
    SURVEY_CREATED_SOURCE,
    SURVEY_RATING_SCALE,
    defaultSurveyAppearance,
    defaultSurveyFieldValues,
} from './constants'
import type { surveyLogicType } from './surveyLogicType'
import { getSurveyStatus, surveysLogic } from './surveysLogic'
import { SurveyFeatureWarning, getSurveyWarnings } from './surveyVersionRequirements'
import {
    DATE_FORMAT,
    type OpenEndedColumnMap,
    type SurveyQueryFilters,
    buildAggregateQuery,
    buildOpenEndedQuery,
    buildPartialResponsesFilter,
    buildSurveyTimestampFilter,
    calculateSurveyRates,
    createAnswerFilterHogQLExpression,
    getExpressionCommentForQuestion,
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

const SURVEY_QUERY_TAG_BASE = { scene: 'Survey' as const, productKey: 'surveys' as const }

const SURVEY_QUERY_TAGS = {
    baseStats: { ...SURVEY_QUERY_TAG_BASE, name: 'survey_base_stats' as const },
    dismissedAndSent: {
        ...SURVEY_QUERY_TAG_BASE,
        name: 'survey_dismissed_sent_overlap' as const,
    },
    aggregateResults: { ...SURVEY_QUERY_TAG_BASE, name: 'survey_results_aggregate' as const },
    openEndedResults: { ...SURVEY_QUERY_TAG_BASE, name: 'survey_results_open_ended' as const },
}

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

type AggregateRow = [string, string, number]
type AggregateEntries = [string, number][]

function processChoiceQuestion(
    question: MultipleSurveyQuestion,
    entries: AggregateEntries,
    questionType: SurveyQuestionType.SingleChoice | SurveyQuestionType.MultipleChoice
): ChoiceQuestionProcessedResponses {
    const totalEntry = entries.find(([l]) => l === '__total__')
    const dataEntries = entries.filter(([l]) => l !== '__total__')
    const predefined = new Set(question.choices ?? [])

    let total = 0
    const noResponseEntry = entries.find(([l]) => l === '__no_response__')
    const noResponseCount = noResponseEntry ? noResponseEntry[1] : 0
    const filteredEntries = dataEntries.filter(([l]) => l !== '__no_response__')

    const data: ChoiceQuestionResponseData[] = filteredEntries
        .map(([label, count]) => {
            if (questionType === SurveyQuestionType.SingleChoice) {
                total += count
            }
            return { label, value: count, isPredefined: predefined.has(label) }
        })
        .sort((a, b) => b.value - a.value)

    if (questionType === SurveyQuestionType.MultipleChoice && totalEntry) {
        total = totalEntry[1]
    }

    // Zero-fill predefined choices (excluding open choice)
    question.choices?.forEach((choice: string, choiceIndex: number) => {
        const isOpenChoice = question.hasOpenChoice && choiceIndex === question.choices.length - 1
        if (!isOpenChoice && !data.some((d) => d.label === choice)) {
            data.push({ label: choice, value: 0, isPredefined: true })
        }
    })

    return {
        type: questionType,
        data,
        totalResponses: total,
        noResponseCount,
    }
}

function processRatingQuestion(
    question: RatingSurveyQuestion,
    entries: AggregateEntries
): ChoiceQuestionProcessedResponses {
    const scaleSize = question.scale === SURVEY_RATING_SCALE.NPS_10_POINT ? 11 : question.scale
    const counts = new Array(scaleSize).fill(0)
    let total = 0

    entries.forEach(([label, count]) => {
        const parsedValue = parseInt(label, 10)
        if (isNaN(parsedValue)) {
            return
        }

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
            counts[arrayIndex] = count
            total += count
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
        noResponseCount: 0,
    }
}

function processOpenQuestion(entries: AggregateEntries): OpenQuestionProcessedResponses {
    const total = entries.find(([l]) => l === '__total__')?.[1] ?? 0
    return { type: SurveyQuestionType.Open, data: [], totalResponses: total }
}

export function processResultsForSurveyQuestions(
    questions: SurveyQuestion[],
    rows: AggregateRow[] | null
): ResponsesByQuestion {
    if (!rows) {
        return {}
    }

    const grouped: Record<string, AggregateEntries> = {}
    for (const [qid, label, count] of rows) {
        if (!grouped[qid]) {
            grouped[qid] = []
        }
        grouped[qid].push([label, count])
    }

    const responsesByQuestion: ResponsesByQuestion = {}

    questions.forEach((question) => {
        // Skip questions without IDs or Link questions
        if (!question.id || !grouped[question.id] || question.type === SurveyQuestionType.Link) {
            return
        }
        const entries = grouped[question.id]

        switch (question.type) {
            case SurveyQuestionType.SingleChoice:
            case SurveyQuestionType.MultipleChoice:
                responsesByQuestion[question.id] = processChoiceQuestion(question, entries, question.type)
                break
            case SurveyQuestionType.Rating:
                responsesByQuestion[question.id] = processRatingQuestion(question, entries)
                break
            case SurveyQuestionType.Open:
                responsesByQuestion[question.id] = processOpenQuestion(entries)
                break
        }
    })

    return responsesByQuestion
}

function collectOpenChoiceResponses(
    question: MultipleSurveyQuestion,
    questionType: SurveyQuestionType,
    rows: any[][],
    columnIndex: number,
    distinctIdIdx: number,
    timestampIdx: number
): ChoiceQuestionResponseData[] {
    const predefined = new Set(question.choices ?? [])
    const otherData: ChoiceQuestionResponseData[] = []

    for (const row of rows) {
        const rawValue = row[columnIndex]
        if (!rawValue) {
            continue
        }

        // Multiple choice values come as string arrays, single choice as a single string
        let choices: string[]
        if (questionType === SurveyQuestionType.MultipleChoice) {
            choices = (rawValue as string[]).map((v) => v.replace(/^['"]+|['"]+$/g, ''))
        } else {
            choices = [rawValue as string]
        }

        for (const choice of choices) {
            if (choice && !predefined.has(choice)) {
                otherData.push({
                    label: choice,
                    value: 1,
                    isPredefined: false,
                    distinctId: row[distinctIdIdx] as string,
                    timestamp: row[timestampIdx] as string,
                })
            }
        }
    }

    return otherData
}

export function processOpenEndedResults(
    questions: SurveyQuestion[],
    columnMap: OpenEndedColumnMap,
    rows: any[][] | null
): ResponsesByQuestion {
    if (!rows) {
        return {}
    }

    const numCols = Object.keys(columnMap).length
    const distinctIdIdx = numCols
    const timestampIdx = numCols + 1
    const result: ResponsesByQuestion = {}

    for (const [questionId, { columnIndex, type }] of Object.entries(columnMap)) {
        if (type === SurveyQuestionType.Open) {
            const data: OpenQuestionResponseData[] = []
            for (const row of rows) {
                const value = row[columnIndex] as string
                if (!value) {
                    continue
                }
                data.push({
                    distinctId: row[distinctIdIdx] as string,
                    response: value,
                    timestamp: row[timestampIdx] as string,
                })
            }
            result[questionId] = { type: SurveyQuestionType.Open, data, totalResponses: data.length }
        } else {
            const question = questions.find((q) => q.id === questionId) as MultipleSurveyQuestion | undefined
            if (!question) {
                continue
            }
            const otherData = collectOpenChoiceResponses(question, type, rows, columnIndex, distinctIdIdx, timestampIdx)
            if (otherData.length > 0) {
                result[questionId] = { type, data: otherData, totalResponses: 0, noResponseCount: 0 }
            }
        }
    }

    return result
}

export function mergeResponsesByQuestion(
    aggregate: ResponsesByQuestion,
    openEnded: ResponsesByQuestion
): ResponsesByQuestion {
    const merged = { ...aggregate }
    for (const [qid, openData] of Object.entries(openEnded)) {
        const agg = merged[qid]
        if (!agg) {
            merged[qid] = openData
        } else if (openData.type === SurveyQuestionType.Open) {
            merged[qid] = { ...openData, totalResponses: agg.totalResponses }
        } else {
            const aggChoice = agg as ChoiceQuestionProcessedResponses
            merged[qid] = { ...aggChoice, data: [...aggChoice.data, ...openData.data] }
        }
    }
    return merged
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
                'reportSurveyConsolidatedResultsQuery',
            ],
            teamLogic,
            ['addProductIntent'],
        ],
        values: [
            enabledFlagLogic,
            ['featureFlags as enabledFlags'],
            surveysLogic,
            ['data', 'teamSdkVersions'],
            userLogic,
            ['user'],
            teamLogic,
            ['currentTeam'],
            propertyDefinitionsModel,
            ['propertyDefinitionsByType'],
            maxGlobalLogic,
            ['dataProcessingAccepted'],
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
        setSelectedPageIndex: (idx: number | null) => ({ idx }),
        setSelectedSection: (section: SurveyEditSection | null) => ({ section }),
        resetTargeting: true,
        resetSurveyAdaptiveSampling: true,
        resetSurveyResponseLimits: true,
        setFlagPropertyErrors: (errors: any) => ({ errors }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[], reloadResults: boolean = true) => ({
            propertyFilters,
            reloadResults,
        }),
        setAnswerFilters: (filters: EventPropertyFilter[], reloadResults: boolean = true) => ({
            filters,
            reloadResults,
        }),
        setDateRange: (dateRange: SurveyDateRange, reloadResults: boolean = true) => ({ dateRange, reloadResults }),
        clearFilters: true,
        setInterval: (interval: IntervalType) => ({ interval }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setFilterSurveyStatsByDistinctId: (filterByDistinctId: boolean) => ({ filterByDistinctId }),
        setBaseStatsResults: (results: SurveyBaseStatsResult) => ({ results }),
        setDismissedAndSentCount: (count: DismissedAndSentCountResult) => ({ count }),
        setShowArchivedResponses: (show: boolean) => ({ show }),
        archiveResponse: (responseUuid: string) => ({ responseUuid }),
        unarchiveResponse: (responseUuid: string) => ({ responseUuid }),
        startResultsRequery: true,
        markResultsRequeryCompleted: true,
        toggleSurveyNotificationEnabled: (notificationId: string, enabled: boolean) => ({
            notificationId,
            enabled,
        }),
        setPersonNames: (personNames: Record<string, string>) => ({ personNames }),
    }),
    loaders(({ props, actions, values }) => ({
        surveyHeadline: [
            null as { headline: string; responses_sampled: number; has_more: boolean } | null,
            {
                loadSurveyHeadline: async (forceRefresh: boolean = false) => {
                    if (props.id === NEW_SURVEY.id || !values.survey?.start_date) {
                        return null
                    }
                    const result = await api.surveys.getSummaryHeadline(props.id, forceRefresh)
                    if (result) {
                        actions.setSurveyValue('headline_summary', result.headline)
                        actions.setSurveyValue('headline_response_count', result.responses_sampled)
                    }
                    return result
                },
            },
        ],
        survey: {
            loadSurvey: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const survey = await api.surveys.get(props.id)
                        // patch surveys with a potentially null appearance...
                        // pending root cause on _how_ these get to be null
                        if (!survey.appearance) {
                            survey.appearance = defaultSurveyAppearance
                        }
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

                        if (!values.dateRange) {
                            actions.setDateRange(
                                {
                                    date_from: getSurveyStartDateForQuery(survey),
                                    date_to: getSurveyEndDateForQuery(survey),
                                },
                                false
                            )
                        }
                        actions.addProductIntent({
                            product_type: ProductKey.SURVEYS,
                            intent_context: ProductIntentContext.SURVEY_VIEWED,
                            metadata: {
                                survey_id: survey.id,
                                survey_status: getSurveyStatus(survey),
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
                    const templatedSurvey = { ...values.survey }
                    templatedSurvey.appearance = {
                        ...defaultSurveyAppearance,
                        ...teamLogic.values.currentTeam?.survey_config?.appearance,
                    }
                    return templatedSurvey
                }

                const newSurvey = { ...NEW_SURVEY }
                newSurvey.appearance = {
                    ...defaultSurveyAppearance,
                    ...teamLogic.values.currentTeam?.survey_config?.appearance,
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
                        ${values.archivedResponsesFilter}
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

                const response = await api.queryHogQL(query, SURVEY_QUERY_TAGS.baseStats, {
                    queryParams: {
                        filters: {
                            properties: values.propertyFilters,
                        },
                    },
                })
                const results = (response.results as SurveyBaseStatsResult | undefined) ?? null
                actions.setBaseStatsResults(results)
                actions.loadConsolidatedSurveyResults()
                return results
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
                            ${values.archivedResponsesFilter}
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

                const response = await api.queryHogQL(query, SURVEY_QUERY_TAGS.dismissedAndSent, {
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
            loadConsolidatedSurveyResults: async (): Promise<ConsolidatedSurveyResults> => {
                if (props.id === NEW_SURVEY.id || !values.survey?.start_date) {
                    return { responsesByQuestion: {} }
                }

                const survey = values.survey as Survey
                const queryFilters: SurveyQueryFilters = {
                    timestampFilter: values.timestampFilter,
                    answerFilterHogQLExpression: values.answerFilterHogQLExpression,
                    archivedResponsesFilter: values.archivedResponsesFilter,
                }
                const queryParams = {
                    queryParams: { filters: { properties: values.propertyFilters } },
                }
                const aggregateQuery = buildAggregateQuery(survey, queryFilters, values.dateRange)
                const openEndedResult = buildOpenEndedQuery(survey, queryFilters, values.dateRange)

                const startMs = performance.now()
                let aggregateDuration = 0
                let openEndedDuration = 0

                const [aggregateResponse, openEndedResponse] = await Promise.all([
                    aggregateQuery
                        ? api
                              .queryHogQL(
                                  aggregateQuery as HogQLQueryString,
                                  SURVEY_QUERY_TAGS.aggregateResults,
                                  queryParams
                              )
                              .then((r) => {
                                  aggregateDuration = performance.now() - startMs
                                  return r
                              })
                        : Promise.resolve({ results: null }),
                    openEndedResult
                        ? api
                              .queryHogQL(
                                  openEndedResult.query as HogQLQueryString,
                                  SURVEY_QUERY_TAGS.openEndedResults,
                                  queryParams
                              )
                              .then((r) => {
                                  openEndedDuration = performance.now() - startMs
                                  return r
                              })
                        : Promise.resolve({ results: null }),
                ])

                const endMs = performance.now()

                actions.reportSurveyConsolidatedResultsQuery(survey, endMs - startMs, {
                    aggregate: aggregateDuration,
                    openEnded: openEndedDuration,
                })

                const aggregate = processResultsForSurveyQuestions(survey.questions, aggregateResponse.results)
                const openEnded = openEndedResult
                    ? processOpenEndedResults(survey.questions, openEndedResult.columnMap, openEndedResponse.results)
                    : {}

                return { responsesByQuestion: mergeResponsesByQuestion(aggregate, openEnded) }
            },
        },
        archivedResponseUuids: [
            new Set<string>(),
            {
                loadArchivedResponseUuids: async (): Promise<Set<string>> => {
                    if (props.id === NEW_SURVEY.id) {
                        return new Set()
                    }
                    const uuids = await api.surveys.getArchivedResponseUuids(props.id)
                    return new Set(uuids)
                },
            },
        ],
        surveyNotifications: [
            [] as HogFunctionType[],
            {
                loadSurveyNotifications: async (): Promise<HogFunctionType[]> => {
                    if (props.id === NEW_SURVEY.id) {
                        return []
                    }
                    const response = await api.hogFunctions.list({
                        filter_groups: [
                            {
                                events: [
                                    {
                                        id: SurveyEventName.SENT,
                                        type: 'events',
                                        properties: [
                                            {
                                                key: SurveyEventProperties.SURVEY_ID,
                                                type: PropertyFilterType.Event,
                                                value: props.id,
                                                operator: PropertyOperator.Exact,
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                        types: ['destination'],
                        full: true,
                    })

                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions, values, cache, props }) => {
        const maybeCompleteResultsRequery = (): void => {
            if (cache.resultsRequeryCompletionTimer) {
                clearTimeout(cache.resultsRequeryCompletionTimer)
            }

            cache.resultsRequeryCompletionTimer = setTimeout(() => {
                cache.resultsRequeryCompletionTimer = null

                const mountedLogic = surveyLogic.findMounted(props)
                if (!mountedLogic?.values.resultsRequeryInProgress || mountedLogic.values.isAnyResultsLoading) {
                    return
                }

                mountedLogic.actions.markResultsRequeryCompleted()
            }, 0)
        }
        const reloadAllSurveyResults = (): void => {
            if (cache.reloadDebounceTimer) {
                clearTimeout(cache.reloadDebounceTimer)
            }

            if (!values.resultsRequeryInProgress) {
                actions.startResultsRequery()
            }

            cache.reloadDebounceTimer = setTimeout(() => {
                actions.loadSurveyBaseStats()
                actions.loadSurveyDismissedAndSentCount()
            }, 300)
        }

        return {
            createSurveySuccess: ({ survey }) => {
                lemonToast.success(<>Survey {survey.name} created</>)
                actions.loadSurveys()
                router.actions.replace(urls.survey(survey.id))
                actions.reportSurveyCreated(survey)
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateSurvey)
            },
            updateSurveySuccess: ({ survey }) => {
                lemonToast.success(<>Survey {survey.name} updated</>)
                actions.editingSurvey(false)
                actions.reportSurveyEdited(survey)
                actions.loadSurveys()
            },
            launchSurveySuccess: ({ survey }) => {
                lemonToast.success(<>Survey {survey.name} launched</>)
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.LaunchSurvey)

                actions.loadSurveys()
            },
            stopSurveySuccess: () => {
                actions.loadSurveys()
            },
            resumeSurveySuccess: () => {
                actions.loadSurveys()
            },
            archiveSurvey: () => {
                const updates: Partial<Survey> & { intentContext?: ProductIntentContext } = {
                    archived: true,
                    intentContext: ProductIntentContext.SURVEY_ARCHIVED,
                }
                if (values.isSurveyRunning) {
                    updates.end_date = dayjs().toISOString()
                }
                actions.updateSurvey(updates)
            },
            loadSurveySuccess: () => {
                // Initialize dataCollectionType from survey data (using selector pattern for consistency)
                actions.setDataCollectionType(values.derivedDataCollectionType)

                if (values.survey.id !== NEW_SURVEY.id && values.survey.start_date) {
                    // Load archived UUIDs first — stats are triggered by loadArchivedResponseUuidsSuccess
                    // so that the archivedResponsesFilter is populated before stats queries run
                    actions.loadArchivedResponseUuids()
                }
            },
            loadArchivedResponseUuidsSuccess: () => {
                // Initial survey load fetches archived UUIDs before any results requery is active.
                // Archive/unarchive flows update this state manually and trigger the results reload explicitly.
                if (
                    values.survey.id !== NEW_SURVEY.id &&
                    values.survey.start_date &&
                    !values.resultsRequeryInProgress
                ) {
                    actions.loadSurveyBaseStats()
                    actions.loadSurveyDismissedAndSentCount()
                }
            },
            loadConsolidatedSurveyResultsSuccess: async ({ consolidatedSurveyResults }) => {
                const distinctIds = new Set<string>()
                for (const data of Object.values(consolidatedSurveyResults.responsesByQuestion)) {
                    for (const r of data.data) {
                        const id = 'distinctId' in r ? r.distinctId : undefined
                        if (id) {
                            distinctIds.add(id)
                        }
                    }
                }

                if (distinctIds.size === 0) {
                    maybeCompleteResultsRequery()
                    return
                }

                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    maybeCompleteResultsRequery()
                    return
                }

                try {
                    const allIds = Array.from(distinctIds)
                    const BATCH_SIZE = 200
                    const personNames: Record<string, string> = {}

                    for (let i = 0; i < allIds.length; i += BATCH_SIZE) {
                        const batch = allIds.slice(i, i + BATCH_SIZE)
                        const response = await api.create(`api/environments/${teamId}/persons/batch_by_distinct_ids/`, {
                            distinct_ids: batch,
                        })

                        for (const [distinctId, person] of Object.entries(
                            response.results as Record<string, { name: string }>
                        )) {
                            if (person.name) {
                                personNames[distinctId] = person.name
                            }
                        }
                    }

                    if (Object.keys(personNames).length > 0) {
                        actions.setPersonNames(personNames)
                    }
                } catch {
                    // Person enrichment is best-effort — don't block survey results
                }

                maybeCompleteResultsRequery()
            },
            loadConsolidatedSurveyResultsFailure: () => {
                maybeCompleteResultsRequery()
            },
            loadSurveyBaseStatsSuccess: () => {
                if (values.isSurveyHeadlineEnabled && values.dataProcessingAccepted) {
                    const currentCount = values.processedSurveyStats?.[SurveyEventName.SENT]?.total_count ?? 0
                    const cachedCount = values.survey.headline_response_count ?? 0

                    if (currentCount > 0) {
                        const needsGeneration = !values.survey.headline_summary
                        const isStale = currentCount > cachedCount + 5

                        if (needsGeneration || isStale) {
                            actions.loadSurveyHeadline(true)
                        }
                    }
                }

                maybeCompleteResultsRequery()
            },
            loadSurveyBaseStatsFailure: () => {
                maybeCompleteResultsRequery()
            },
            loadSurveyDismissedAndSentCountSuccess: () => {
                maybeCompleteResultsRequery()
            },
            loadSurveyDismissedAndSentCountFailure: () => {
                maybeCompleteResultsRequery()
            },
            startResultsRequery: () => {
                lemonToast.loading('Refreshing results...', {
                    toastId: LOADING_SURVEY_RESULTS_TOAST_ID,
                    autoClose: false,
                })
            },
            markResultsRequeryCompleted: () => {
                lemonToast.dismiss(LOADING_SURVEY_RESULTS_TOAST_ID)
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
                } else if (
                    values.surveyErrors.questions != null &&
                    !values.surveyErrors.questions.every((q) => q.question === false)
                ) {
                    actions.setSelectedSection(SurveyEditSection.Steps)
                    const page = values.surveyErrors.questions.findIndex((q) => q.question !== false)
                    if (page >= 0) {
                        actions.setSelectedPageIndex(page)
                    }
                } else if (hasFormErrors(values.surveyErrors?.appearance)) {
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
            setPropertyFilters: ({ reloadResults }) => {
                if (reloadResults) {
                    reloadAllSurveyResults()
                }
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
            clearFilters: () => {
                const survey = values.survey as Survey
                actions.setAnswerFilters(values.defaultAnswerFilters, false)
                actions.setPropertyFilters([], false)
                actions.setDateRange(
                    {
                        date_from: getSurveyStartDateForQuery(survey),
                        date_to: getSurveyEndDateForQuery(survey),
                    },
                    false
                )
                reloadAllSurveyResults()
            },
            setShowArchivedResponses: () => {
                reloadAllSurveyResults()
            },
            archiveResponse: async ({ responseUuid }) => {
                try {
                    actions.startResultsRequery()
                    await api.surveys.archiveResponse(values.survey.id, responseUuid)

                    const updatedUuids = new Set<string>(values.archivedResponseUuids)
                    updatedUuids.add(responseUuid)
                    actions.loadArchivedResponseUuidsSuccess(updatedUuids)
                    actions.loadSurveyBaseStats()
                    actions.loadSurveyDismissedAndSentCount()

                    lemonToast.success('Response archived')
                } catch (error) {
                    actions.markResultsRequeryCompleted()
                    lemonToast.error('Failed to archive response')
                    posthog.captureException(error, {
                        action: 'archive-survey-response',
                        survey: values.survey.id,
                        response: responseUuid,
                    })
                    actions.loadArchivedResponseUuids()
                }
            },
            unarchiveResponse: async ({ responseUuid }) => {
                try {
                    actions.startResultsRequery()
                    await api.surveys.unarchiveResponse(values.survey.id, responseUuid)

                    const updatedUuids = new Set<string>(values.archivedResponseUuids)
                    updatedUuids.delete(responseUuid)
                    actions.loadArchivedResponseUuidsSuccess(updatedUuids)
                    actions.loadSurveyBaseStats()
                    actions.loadSurveyDismissedAndSentCount()

                    lemonToast.success('Response unarchived')
                } catch (error) {
                    actions.markResultsRequeryCompleted()
                    lemonToast.error('Failed to unarchive response')
                    posthog.captureException(error, {
                        action: 'unarchive-survey-response',
                        survey: values.survey.id,
                        response: responseUuid,
                    })
                    actions.loadArchivedResponseUuids()
                }
            },
            toggleSurveyNotificationEnabled: async ({ notificationId, enabled }) => {
                const updatedNotifications = values.surveyNotifications.map((notification) =>
                    notification.id === notificationId ? { ...notification, enabled } : notification
                )
                actions.loadSurveyNotificationsSuccess(updatedNotifications)

                try {
                    await api.hogFunctions.update(notificationId, { enabled })
                } catch (error) {
                    lemonToast.error('Failed to update notification')
                    actions.loadSurveyNotifications()
                    posthog.captureException(error, {
                        action: 'toggle-survey-notification',
                        survey: values.survey.id,
                        notification: notificationId,
                    })
                }
            },
        }
    }),
    events(({ cache }) => ({
        beforeUnmount: () => {
            if (cache.reloadDebounceTimer) {
                clearTimeout(cache.reloadDebounceTimer)
                cache.reloadDebounceTimer = null
            }

            if (cache.resultsRequeryCompletionTimer) {
                clearTimeout(cache.resultsRequeryCompletionTimer)
                cache.resultsRequeryCompletionTimer = null
            }
        },
    })),
    reducers({
        personNames: [
            {} as Record<string, string>,
            {
                setPersonNames: (state, { personNames }) => ({ ...state, ...personNames }),
            },
        ],
        showArchivedResponses: [
            false,
            { persist: true },
            {
                setShowArchivedResponses: (_, { show }) => show,
            },
        ],
        filterSurveyStatsByDistinctId: [
            true,
            { persist: true },
            {
                setFilterSurveyStatsByDistinctId: (_, { filterByDistinctId }) => filterByDistinctId,
            },
        ],
        resultsRequeryInProgress: [
            false,
            {
                startResultsRequery: () => true,
                markResultsRequeryCompleted: () => false,
                loadSurveySuccess: () => false,
                resetSurvey: () => false,
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
        enrichedConsolidatedSurveyResults: [
            (s) => [s.consolidatedSurveyResults, s.personNames],
            (results: ConsolidatedSurveyResults, personNames: Record<string, string>): ConsolidatedSurveyResults => {
                if (!results?.responsesByQuestion || Object.keys(personNames).length === 0) {
                    return results
                }

                const enriched: ResponsesByQuestion = {}
                for (const [qid, data] of Object.entries(results.responsesByQuestion)) {
                    enriched[qid] = {
                        ...data,
                        data: data.data.map((r) => {
                            const id = 'distinctId' in r ? r.distinctId : undefined
                            return id && personNames[id] ? { ...r, personDisplayName: personNames[id] } : r
                        }),
                    } as typeof data
                }

                return { responsesByQuestion: enriched }
            },
        ],
        timestampFilter: [
            (s) => [s.survey, s.dateRange],
            (survey: Survey, dateRange: SurveyDateRange): string => {
                return buildSurveyTimestampFilter(survey, dateRange)
            },
        ],
        partialResponsesFilter: [
            (s) => [s.survey, s.dateRange],
            (survey: Survey, dateRange: SurveyDateRange): string => {
                if (survey.enable_partial_responses) {
                    return buildPartialResponsesFilter(survey, dateRange)
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
        archivedResponsesFilter: [
            (s) => [s.showArchivedResponses, s.archivedResponseUuids],
            (showArchivedResponses: boolean, archivedUuids: Set<string>): string => {
                if (showArchivedResponses || !archivedUuids || archivedUuids.size === 0) {
                    return ''
                }

                // UUIDs are pre-validated by Django's UUIDField when stored in SurveyResponseArchive
                const uuidList = Array.from(archivedUuids)
                    .map((uuid) => `'${uuid}'`)
                    .join(', ')
                return `AND uuid NOT IN (${uuidList})`
            },
        ],
        archivedResponsesPropertyFilter: [
            (s) => [s.showArchivedResponses, s.archivedResponseUuids],
            (
                showArchivedResponses: boolean,
                archivedUuids: Set<string>
            ): Array<{ type: PropertyFilterType.HogQL; key: string }> => {
                if (showArchivedResponses || !archivedUuids || archivedUuids.size === 0) {
                    return []
                }

                // UUIDs are pre-validated by Django's UUIDField when stored in SurveyResponseArchive
                const uuidList = Array.from(archivedUuids)
                    .map((uuid) => `'${uuid}'`)
                    .join(', ')
                return [
                    {
                        type: PropertyFilterType.HogQL,
                        key: `uuid NOT IN (${uuidList})`,
                    },
                ]
            },
        ],
        isAdaptiveLimitFFEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.SURVEYS_ADAPTIVE_LIMITS]
            },
        ],
        isSurveyHeadlineEnabled: [
            (s) => [s.enabledFlags],
            (enabledFlags: FeatureFlagsSet): boolean => {
                return !!enabledFlags[FEATURE_FLAGS.SURVEY_HEADLINE_SUMMARY]
            },
        ],
        isAnyResultsLoading: [
            (s) => [
                s.archivedResponseUuidsLoading,
                s.surveyBaseStatsLoading,
                s.surveyDismissedAndSentCountLoading,
                s.consolidatedSurveyResultsLoading,
            ],
            (
                archivedResponseUuidsLoading: boolean,
                surveyBaseStatsLoading: boolean,
                surveyDismissedAndSentCountLoading: boolean,
                consolidatedSurveyResultsLoading: boolean
            ) => {
                return (
                    archivedResponseUuidsLoading ||
                    consolidatedSurveyResultsLoading ||
                    surveyBaseStatsLoading ||
                    surveyDismissedAndSentCountLoading
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
        hasActiveAnswerFilters: [
            (s) => [s.answerFilters],
            (answerFilters: EventPropertyFilter[]): boolean => {
                return answerFilters.some((filter) => {
                    if (!filter?.value) {
                        return false
                    }
                    return Array.isArray(filter.value) ? filter.value.length > 0 : filter.value !== ''
                })
            },
        ],
        hasActiveDateRange: [
            (s) => [s.dateRange, s.survey],
            (dateRange: SurveyDateRange | null, survey: Survey): boolean => {
                const surveyStartDate = getSurveyStartDateForQuery(survey)
                const surveyEndDate = getSurveyEndDateForQuery(survey)
                return !!dateRange && (dateRange.date_from !== surveyStartDate || dateRange.date_to !== surveyEndDate)
            },
        ],
        hasActiveFilters: [
            (s) => [s.hasActiveAnswerFilters, s.propertyFilters, s.hasActiveDateRange],
            (
                hasActiveAnswerFilters: boolean,
                propertyFilters: AnyPropertyFilter[],
                hasActiveDateRange: boolean
            ): boolean => {
                return hasActiveAnswerFilters || propertyFilters.length > 0 || hasActiveDateRange
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
        derivedDataCollectionType: [
            (s) => [s.surveyUsesAdaptiveLimit, s.surveyUsesLimit, s.isAdaptiveLimitFFEnabled],
            (
                surveyUsesAdaptiveLimit: boolean,
                surveyUsesLimit: boolean,
                isAdaptiveLimitFFEnabled: boolean
            ): DataCollectionType => {
                if (isAdaptiveLimitFFEnabled && surveyUsesAdaptiveLimit) {
                    return 'until_adaptive_limit'
                } else if (surveyUsesLimit) {
                    return 'until_limit'
                }
                return 'until_stopped'
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
                          access_control_resource: 'survey',
                          access_control_resource_id: `${survey.id}`,
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
            (s) => [
                s.survey,
                s.propertyFilters,
                s.answerFilterHogQLExpression,
                s.partialResponsesFilter,
                s.archivedResponsesFilter,
                s.dateRange,
                s.archivedResponseUuids,
                s.showArchivedResponses,
            ],
            (
                survey: Survey,
                propertyFilters: AnyPropertyFilter[],
                answerFilterHogQLExpression: string,
                partialResponsesFilter: string,
                archivedResponsesFilter: string,
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

                if (archivedResponsesFilter !== '') {
                    // skip the 'AND ' prefix
                    where.push(archivedResponsesFilter.substring(4))
                }

                const defaultColumns = [
                    '*',
                    ...survey.questions.map((q, i) => {
                        if (q.type === SurveyQuestionType.MultipleChoice) {
                            return `arrayStringConcat(${getSurveyResponse(q, i)}, ', ') -- ${getExpressionCommentForQuestion(q, i)}`
                        }
                        return `${getSurveyResponse(q, i)} -- ${getExpressionCommentForQuestion(q, i)}`
                    }),
                    'timestamp',
                    'person',
                    `coalesce(JSONExtractString(properties, '$lib_version')) -- Library Version`,
                    `coalesce(JSONExtractString(properties, '$lib')) -- Library`,
                    `coalesce(JSONExtractString(properties, '$current_url')) -- URL`,
                ]

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: defaultColumns,
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
                    defaultColumns,
                    propertiesViaUrl: true,
                    showExport: true,
                    showReload: true,
                    showRecordingColumn: true,
                    showEventFilter: false,
                    showPropertyFilter: false,
                    showTimings: false,
                    showPersistentColumnConfigurator: true,
                    contextKey: `survey:${survey.id}`,
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
        urlSearchParams: [
            (s) => [s.propertyFilters, s.answerFilters, s.dateRange, s.survey],
            (
                propertyFilters: AnyPropertyFilter[],
                answerFilters: EventPropertyFilter[],
                dateRange: SurveyDateRange | null,
                survey: Survey
            ) => {
                const defaultDateFrom = getSurveyStartDateForQuery(survey)
                const defaultDateTo = getSurveyEndDateForQuery(survey)

                const nonEmptyAnswerFilters = answerFilters?.filter((filter) => {
                    const value = filter.value
                    if (Array.isArray(value)) {
                        return value.length > 0
                    }
                    return value !== null && value !== undefined && value !== ''
                })

                const isDefaultDateRange =
                    dateRange?.date_from === defaultDateFrom && dateRange?.date_to === defaultDateTo

                return objectClean({
                    ...router.values.searchParams,
                    propertyFilters: propertyFilters?.length > 0 ? JSON.stringify(propertyFilters) : undefined,
                    answerFilters:
                        nonEmptyAnswerFilters?.length > 0 ? JSON.stringify(nonEmptyAnswerFilters) : undefined,
                    date_from: !isDefaultDateRange && dateRange?.date_from ? dateRange.date_from : undefined,
                    date_to: !isDefaultDateRange && dateRange?.date_to ? dateRange.date_to : undefined,
                })
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
            (s) => [s.enrichedConsolidatedSurveyResults, s.survey],
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
        surveyWarnings: [
            (s) => [s.survey, s.teamSdkVersions],
            (survey, teamSdkVersions): SurveyFeatureWarning[] => {
                return getSurveyWarnings(survey as Survey, teamSdkVersions)
            },
        ],
    }),
    forms(({ actions, props, values }) => ({
        survey: {
            defaults: {
                ...NEW_SURVEY,
                appearance: {
                    ...defaultSurveyAppearance,
                    ...teamLogic.values.currentTeam?.survey_config?.appearance,
                },
            } as NewSurvey | Survey,
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
                                choices:
                                    !question.choices?.length || question.choices.some((choice) => !choice.trim())
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
                    lemonToast.error('Your survey contains an endless cycle. Please revisit your branching rules.')
                    return
                }
                const payload = sanitizeSurvey(surveyPayload, { keepEmptyConditions: true })

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
        [urls.survey(props.id ?? 'new')]: (_, searchParams, { fromTemplate }, { method }) => {
            // Preserve unsaved edits whenever we re-enter the same survey URL — covers
            // both explicit opt-in navigations (e.g. guided↔full editor switch) and
            // implicit re-entries like tab switching, which also dispatch a PUSH.
            const shouldPreserveLocalChanges = values.surveyChanged && values.survey.id === (props.id ?? NEW_SURVEY.id)

            // Parse filters from URL params
            if (searchParams.propertyFilters) {
                try {
                    const parsedPropertyFilters = JSON.parse(searchParams.propertyFilters)
                    if (Array.isArray(parsedPropertyFilters) && parsedPropertyFilters.length > 0) {
                        actions.setPropertyFilters(parsedPropertyFilters)
                    }
                } catch (e) {
                    console.error('Failed to parse propertyFilters from URL:', e)
                }
            }

            if (searchParams.answerFilters) {
                try {
                    const parsedAnswerFilters = JSON.parse(searchParams.answerFilters)
                    if (Array.isArray(parsedAnswerFilters) && parsedAnswerFilters.length > 0) {
                        const mergedFilters =
                            values.answerFilters.length > 0
                                ? values.answerFilters.map((existingFilter) => {
                                      const urlFilter = parsedAnswerFilters.find(
                                          (f: EventPropertyFilter) => f.key === existingFilter.key
                                      )
                                      return urlFilter ?? existingFilter
                                  })
                                : parsedAnswerFilters
                        actions.setAnswerFilters(mergedFilters, false)
                    }
                } catch (e) {
                    console.error('Failed to parse answerFilters from URL:', e)
                }
            }

            if (searchParams.date_from || searchParams.date_to) {
                actions.setDateRange(
                    {
                        date_from: searchParams.date_from || null,
                        date_to: searchParams.date_to || null,
                    },
                    false
                )
            }

            // We always set the editingSurvey to true when we create a new survey
            if (props.id === 'new') {
                actions.editingSurvey(true)
            }
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (shouldPreserveLocalChanges) {
                    if (searchParams.edit) {
                        actions.editingSurvey(true)
                    }
                    return
                }
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

            if (searchParams.edit) {
                actions.editingSurvey(true)
            }
        },
    })),
    actionToUrl(({ values }) => ({
        editingSurvey: ({ editing }) => {
            const searchParams = router.values.searchParams
            if (editing) {
                searchParams['edit'] = true
            } else {
                delete searchParams['edit']
            }

            return [router.values.location.pathname, router.values.searchParams, router.values.hashParams]
        },
        setPropertyFilters: () => [
            router.values.location.pathname,
            values.urlSearchParams,
            router.values.hashParams,
            { replace: true },
        ],
        setAnswerFilters: () => [
            router.values.location.pathname,
            values.urlSearchParams,
            router.values.hashParams,
            { replace: true },
        ],
        setDateRange: () => [
            router.values.location.pathname,
            values.urlSearchParams,
            router.values.hashParams,
            { replace: true },
        ],
    })),
    afterMount(({ props, actions, values }) => {
        const shouldPreserveLocalChanges =
            router.values.hashParams.preserveLocalChanges && values.surveyChanged && values.survey.id === props.id

        if (props.id !== 'new' && !shouldPreserveLocalChanges) {
            actions.loadSurvey()
            actions.loadSurveyNotifications()
        }
        if (props.id === 'new' && !shouldPreserveLocalChanges) {
            actions.resetSurvey()
        }
    }),
])
