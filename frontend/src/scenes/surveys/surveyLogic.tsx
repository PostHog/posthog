import { lemonToast } from '@posthog/lemon-ui'
import { kea, path, props, key, listeners, afterMount, reducers, actions, selectors, connect } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import {
    Breadcrumb,
    FeatureFlagFilters,
    PluginType,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyQuestionType,
    SurveyType,
} from '~/types'
import type { surveyLogicType } from './surveyLogicType'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { surveysLogic } from './surveysLogic'
import { dayjs } from 'lib/dayjs'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

export interface NewSurvey
    extends Pick<
        Survey,
        | 'id'
        | 'name'
        | 'description'
        | 'type'
        | 'conditions'
        | 'questions'
        | 'start_date'
        | 'end_date'
        | 'linked_flag'
        | 'targeting_flag'
        | 'archived'
        | 'appearance'
    > {
    linked_flag_id: number | undefined
    targeting_flag_filters: Pick<FeatureFlagFilters, 'groups'> | undefined
}

export const defaultSurveyAppearance = {
    backgroundColor: 'white',
    submitButtonColor: '#2C2C2C',
    textColor: 'black',
    submitButtonText: 'Submit',
    descriptionTextColor: 'black',
}

const NEW_SURVEY: NewSurvey = {
    id: 'new',
    name: '',
    description: '',
    questions: [{ type: SurveyQuestionType.Open, question: '', link: null }],
    type: SurveyType.Popover,
    linked_flag_id: undefined,
    targeting_flag_filters: undefined,
    linked_flag: null,
    targeting_flag: null,
    start_date: null,
    end_date: null,
    conditions: null,
    archived: false,
    appearance: defaultSurveyAppearance,
}

export const surveyEventName = 'survey sent'

const SURVEY_RESPONSE_PROPERTY = '$survey_response'

export const getSurveyDataQuery = (survey: Survey): DataTableNode => {
    const surveyDataQuery: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: ['*', `properties.${SURVEY_RESPONSE_PROPERTY}`, 'timestamp', 'person'],
            orderBy: ['timestamp DESC'],
            where: [`event == 'survey sent' or event == '${survey.name} survey sent'`],
            after: survey.created_at,
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
    }
    return surveyDataQuery
}

export const getSurveyMetricsQueries = (surveyId: string): SurveyMetricsQueries => {
    const surveysShownHogqlQuery = `select count(distinct person.id) as 'survey shown' from events where event == 'survey shown' and properties.$survey_id == '${surveyId}'`
    const surveysDismissedHogqlQuery = `select count(distinct person.id) as 'survey dismissed' from events where event == 'survey dismissed' and properties.$survey_id == '${surveyId}'`
    return {
        surveysShown: {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.HogQLQuery, query: surveysShownHogqlQuery },
        },
        surveysDismissed: {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.HogQLQuery, query: surveysDismissedHogqlQuery },
        },
    }
}

export interface SurveyLogicProps {
    id: string | 'new'
}

export interface SurveyMetricsQueries {
    surveysShown: DataTableNode
    surveysDismissed: DataTableNode
}

export const surveyLogic = kea<surveyLogicType>([
    path(['scenes', 'surveys', 'surveyLogic']),
    props({} as SurveyLogicProps),
    key(({ id }) => id),
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
                'reportSurveyViewed',
            ],
        ],
        values: [pluginsLogic, ['installedPlugins', 'enabledPlugins']],
    })),
    actions({
        editingSurvey: (editing: boolean) => ({ editing }),
        launchSurvey: true,
        stopSurvey: true,
        archiveSurvey: true,
        setDataTableQuery: (query: DataTableNode) => ({ query }),
        setSurveyMetricsQueries: (surveyMetricsQueries: SurveyMetricsQueries) => ({ surveyMetricsQueries }),
        setHasTargetingFlag: (hasTargetingFlag: boolean) => ({ hasTargetingFlag }),
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
        },
    })),
    listeners(({ actions }) => ({
        loadSurveySuccess: ({ survey }) => {
            if (survey.start_date && survey.id !== 'new') {
                actions.setDataTableQuery(getSurveyDataQuery(survey as Survey))
                actions.setSurveyMetricsQueries(getSurveyMetricsQueries(survey.id))
            }
            if (survey.targeting_flag) {
                actions.setHasTargetingFlag(true)
            }
        },
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
            actions.setSurveyMetricsQueries(getSurveyMetricsQueries(survey.id))
            actions.setDataTableQuery(getSurveyDataQuery(survey))
            actions.loadSurveys()
            actions.reportSurveyLaunched(survey)
        },
        stopSurveySuccess: ({ survey }) => {
            actions.loadSurveys()
            actions.reportSurveyStopped(survey)
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
        dataTableQuery: [
            null as DataTableNode | null,
            {
                setDataTableQuery: (_, { query }) => query,
            },
        ],
        surveyMetricsQueries: [
            null as SurveyMetricsQueries | null,
            {
                setSurveyMetricsQueries: (_, { surveyMetricsQueries }) => surveyMetricsQueries,
            },
        ],
        hasTargetingFlag: [
            false,
            {
                setHasTargetingFlag: (_, { hasTargetingFlag }) => hasTargetingFlag,
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
            (s) => [s.survey, s.enabledPlugins],
            (survey: Survey, enabledPlugins: PluginType[]): boolean => {
                return !!(
                    survey.type !== SurveyType.API && !enabledPlugins.find((plugin) => plugin.name === 'Surveys app')
                )
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
                })),
            }),
            submit: async (surveyPayload) => {
                let surveyPayloadWithTargetingFlagFilters = surveyPayload
                const flagLogic = featureFlagLogic({ id: values.survey.targeting_flag?.id || 'new' })
                const targetingFlag = flagLogic.values.featureFlag
                if (values.hasTargetingFlag) {
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
