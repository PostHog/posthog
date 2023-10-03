import { lemonToast } from '@posthog/lemon-ui'
import { kea, path, props, key, listeners, afterMount, reducers, actions, selectors, connect } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import {
    Breadcrumb,
    ChartDisplayType,
    PluginType,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyQuestionBase,
    SurveyQuestionType,
    SurveyType,
} from '~/types'
import type { surveyLogicType } from './surveyLogicType'
import { DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema'
import { surveysLogic } from './surveysLogic'
import { dayjs } from 'lib/dayjs'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagLogic as enabledFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import {
    defaultSurveyFieldValues,
    SURVEY_EVENT_NAME,
    SURVEY_RESPONSE_PROPERTY,
    NEW_SURVEY,
    NewSurvey,
} from './constants'

export interface SurveyLogicProps {
    id: string | 'new'
}

export interface SurveyMetricsQueries {
    surveysShown: DataTableNode
    surveysDismissed: DataTableNode
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
            ],
        ],
        values: [
            pluginsLogic,
            ['installedPlugins', 'loading as pluginsLoading', 'enabledPlugins'],
            enabledFlagLogic,
            ['featureFlags as enabledFlags'],
        ],
    })),
    actions({
        editingSurvey: (editing: boolean) => ({ editing }),
        setDefaultForQuestionType: (
            type: SurveyQuestionType,
            isEditingQuestion: boolean,
            isEditingDescription: boolean,
            isEditingThankYouMessage: boolean
        ) => ({
            type,
            isEditingQuestion,
            isEditingDescription,
            isEditingThankYouMessage,
        }),
        launchSurvey: true,
        stopSurvey: true,
        archiveSurvey: true,
        resumeSurvey: true,
    }),
    loaders(({ props, actions }) => ({
        survey: {
            loadSurvey: async () => {
                if (props.id && props.id !== 'new') {
                    const survey = await api.surveys.get(props.id)
                    actions.reportSurveyViewed(survey)
                    return survey
                }
                return { ...NEW_SURVEY }
            },
            createSurvey: async (surveyPayload) => {
                return await api.surveys.create(surveyPayload)
            },
            updateSurvey: async (surveyPayload) => {
                return await api.surveys.update(props.id, surveyPayload)
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
    })),
    listeners(({ actions }) => ({
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
        archiveSurvey: async () => {
            actions.updateSurvey({ archived: true })
        },
    })),
    reducers({
        isEditingSurvey: [
            false,
            {
                editingSurvey: (_, { editing }) => editing,
            },
        ],
        survey: [
            { ...NEW_SURVEY } as NewSurvey | Survey,
            {
                setDefaultForQuestionType: (
                    state,
                    { type, isEditingQuestion, isEditingDescription, isEditingThankYouMessage }
                ) => {
                    const question = isEditingQuestion
                        ? state.questions[0].question
                        : defaultSurveyFieldValues[type].questions[0].question
                    const description = isEditingDescription
                        ? state.questions[0].description
                        : defaultSurveyFieldValues[type].questions[0].description
                    const thankYouMessageHeader = isEditingThankYouMessage
                        ? state.appearance.thankYouMessageHeader
                        : defaultSurveyFieldValues[type].appearance.thankYouMessageHeader

                    return {
                        ...state,
                        questions: [
                            {
                                ...state.questions[0],
                                ...(defaultSurveyFieldValues[type].questions[0] as SurveyQuestionBase),
                                question,
                                description,
                            },
                        ],
                        appearance: {
                            ...state.appearance,
                            ...defaultSurveyFieldValues[type].appearance,
                            thankYouMessageHeader,
                        },
                    }
                },
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
        breadcrumbs: [
            (s) => [s.survey],
            (survey: Survey): Breadcrumb[] => [
                {
                    name: 'Surveys',
                    path: urls.surveys(),
                },
                ...(survey?.name ? [{ name: survey.name }] : []),
            ],
        ],
        surveyPlugin: [
            (s) => [s.installedPlugins],
            (installedPlugins: PluginType[]): PluginType | undefined => {
                // TODO: add more sturdy check for the survey plugin
                return installedPlugins.find((plugin) => plugin.name === 'Surveys app')
            },
        ],
        showSurveyAppWarning: [
            (s) => [s.survey, s.enabledPlugins, s.pluginsLoading, s.enabledFlags],
            (survey: Survey, enabledPlugins: PluginType[], pluginsLoading: boolean, enabledFlags): boolean => {
                return (
                    !enabledFlags[FEATURE_FLAGS.SURVEYS_SITE_APP_DEPRECATION] &&
                    !!(
                        survey.type !== SurveyType.API &&
                        !pluginsLoading &&
                        !enabledPlugins.find((plugin) => plugin.name === 'Surveys app')
                    )
                )
            },
        ],
        dataTableQuery: [
            (s) => [s.survey],
            (survey): DataTableNode | null => {
                if (survey.id === 'new') {
                    return null
                }
                const createdAt = (survey as Survey).created_at

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: ['*', `properties.${SURVEY_RESPONSE_PROPERTY}`, 'timestamp', 'person'],
                        orderBy: ['timestamp DESC'],
                        where: [`event == 'survey sent'`],
                        after: createdAt,
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
                    showEventFilter: true,
                    showPropertyFilter: true,
                    showTimings: false,
                }
            },
        ],
        surveyMetricsQueries: [
            (s) => [s.survey],
            (survey): SurveyMetricsQueries | null => {
                const surveyId = survey.id
                if (surveyId === 'new') {
                    return null
                }
                const startDate = dayjs((survey as Survey).created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                const surveysShownHogqlQuery = `select count(distinct person.id) as 'survey shown' from events where event == 'survey shown' and properties.$survey_id == '${surveyId}' and timestamp >= '${startDate}' and timestamp <= '${endDate}' `
                const surveysDismissedHogqlQuery = `select count(distinct person.id) as 'survey dismissed' from events where event == 'survey dismissed' and properties.$survey_id == '${surveyId}' and timestamp >= '${startDate}' and timestamp <= '${endDate}'`
                return {
                    surveysShown: {
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: surveysShownHogqlQuery,
                        },
                        showTimings: false,
                    },
                    surveysDismissed: {
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: surveysDismissedHogqlQuery,
                        },
                        showTimings: false,
                    },
                }
            },
        ],
        surveyRatingQuery: [
            (s) => [s.survey],
            (survey): InsightVizNode | null => {
                if (survey.id === 'new') {
                    return null
                }
                const startDate = dayjs((survey as Survey).created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                return {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        dateRange: {
                            date_from: startDate,
                            date_to: endDate,
                        },
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$survey_id',
                                operator: PropertyOperator.Exact,
                                value: survey.id,
                            },
                        ],
                        series: [{ event: SURVEY_EVENT_NAME, kind: NodeKind.EventsNode }],
                        trendsFilter: { display: ChartDisplayType.ActionsBarValue },
                        breakdown: { breakdown: '$survey_response', breakdown_type: 'event' },
                    },
                    showTable: true,
                }
            },
        ],
        surveyMultipleChoiceQuery: [
            (s) => [s.survey],
            (survey): DataTableNode | null => {
                if (survey.id === 'new') {
                    return null
                }

                const startDate = dayjs((survey as Survey).created_at).format('YYYY-MM-DD')
                const endDate = survey.end_date
                    ? dayjs(survey.end_date).add(1, 'day').format('YYYY-MM-DD')
                    : dayjs().add(1, 'day').format('YYYY-MM-DD')

                const singleChoiceQuery = `select count(), properties.$survey_response as choice from events where event == 'survey sent' and properties.$survey_id == '${survey.id}' and timestamp >= '${startDate}' and timestamp <= '${endDate}' group by choice order by count() desc`
                const multipleChoiceQuery = `select count(), arrayJoin(JSONExtractArrayRaw(properties, '$survey_response')) as choice from events where event == 'survey sent' and properties.$survey_id == '${survey.id}' and timestamp >= '${startDate}' and timestamp <= '${endDate}'  group by choice order by count() desc`
                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query:
                            survey.questions[0].type === SurveyQuestionType.SingleChoice
                                ? singleChoiceQuery
                                : multipleChoiceQuery,
                    },
                    showTimings: false,
                }
            },
        ],
        hasTargetingFlag: [
            (s) => [s.survey],
            (survey): boolean => {
                return !!survey.targeting_flag || !!survey.targeting_flag_filters
            },
        ],
    }),
    forms(({ actions, props, values }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name, questions }) => ({
                name: !name && 'Please enter a name.',
                questions: questions.map((question) => ({
                    question: !question.question && 'Please enter a question.',
                    ...(question.type === SurveyQuestionType.Link
                        ? { link: !question.link && 'Please enter a url for the link.' }
                        : {}),
                    ...(question.type === SurveyQuestionType.Rating
                        ? {
                              display: !question.display && 'Please choose a display type.',
                              scale: !question.scale && 'Please choose a scale.',
                          }
                        : {}),
                })),
            }),
            submit: async (surveyPayload) => {
                let surveyPayloadWithTargetingFlagFilters = surveyPayload
                const flagLogic = featureFlagLogic({ id: values.survey.targeting_flag?.id || 'new' })
                if (values.hasTargetingFlag) {
                    const targetingFlag = flagLogic.values.featureFlag
                    surveyPayloadWithTargetingFlagFilters = {
                        ...surveyPayload,
                        ...{ targeting_flag_filters: targetingFlag.filters },
                    }
                }
                if (props.id && props.id !== 'new') {
                    actions.updateSurvey(surveyPayloadWithTargetingFlagFilters)
                } else {
                    actions.createSurvey(surveyPayloadWithTargetingFlagFilters)
                }
            },
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.survey(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadSurvey()
                } else {
                    actions.resetSurvey()
                }
            }
        },
    })),
    afterMount(async ({ props, actions }) => {
        if (props.id !== 'new') {
            await actions.loadSurvey()
        }
        if (props.id === 'new') {
            actions.resetSurvey()
        }
    }),
])
