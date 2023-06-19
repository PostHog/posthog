import { lemonToast } from '@posthog/lemon-ui'
import { kea, path, props, key, listeners, afterMount, reducers, actions, selectors, connect } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import {
    AnyPropertyFilter,
    Breadcrumb,
    FeatureFlagFilters,
    FeatureFlagGroupType,
    PluginType,
    Survey,
    SurveyQuestionType,
    SurveyType,
} from '~/types'
import type { surveyLogicType } from './surveyLogicType'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { surveysLogic } from './surveysLogic'
import { dayjs } from 'lib/dayjs'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType } from 'scenes/plugins/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export interface NewSurvey
    extends Pick<
        Survey,
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
    > {
    linked_flag_id: number | undefined
    targeting_flag_filters: Pick<FeatureFlagFilters, 'groups'> | undefined
}

const NEW_SURVEY: NewSurvey = {
    name: '',
    description: '',
    questions: [{ type: SurveyQuestionType.Open, question: '' }],
    type: SurveyType.Popover,
    linked_flag_id: undefined,
    targeting_flag_filters: undefined,
    linked_flag: null,
    targeting_flag: null,
    start_date: null,
    end_date: null,
    conditions: null,
    archived: false,
}

export const getSurveyEventName = (surveyName: string): string => {
    return `${surveyName} survey sent`
}

const SURVEY_RESPONSE_PROPERTY = '$survey_response'

export const getSurveyDataQuery = (surveyName: string): DataTableNode => {
    const surveyDataQuery: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', `properties.${SURVEY_RESPONSE_PROPERTY}`, 'timestamp', 'person'],
            orderBy: ['timestamp DESC'],
            after: '-30d',
            limit: 100,
            event: getSurveyEventName(surveyName),
        },
        propertiesViaUrl: true,
        showExport: true,
        showReload: true,
        showColumnConfigurator: true,
        showEventFilter: true,
        showPropertyFilter: true,
    }
    return surveyDataQuery
}

export interface SurveyLogicProps {
    id: string | 'new'
}

export const surveyLogic = kea<surveyLogicType>([
    path(['scenes', 'surveys', 'surveyLogic']),
    props({} as SurveyLogicProps),
    key(({ id }) => id),
    connect(() => ({
        actions: [
            surveysLogic,
            ['loadSurveys'],
            pluginsLogic,
            ['installPlugin'],
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
        values: [pluginsLogic, ['installedPlugins']],
    })),
    actions({
        editingSurvey: (editing: boolean) => ({ editing }),
        setTargetingFlagFilters: (groups: FeatureFlagGroupType[]) => ({ groups }),
        updateTargetingFlagFilters: (index: number, properties: AnyPropertyFilter[]) => ({ index, properties }),
        addConditionSet: true,
        removeConditionSet: (index: number) => ({ index }),
        setInstallingPlugin: (installing: boolean) => ({ installing }),
        launchSurvey: true,
        installSurveyPlugin: true,
        stopSurvey: true,
        archiveSurvey: true,
        setDataTableQuery: (query: DataTableNode) => ({ query }),
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
            if (survey.start_date) {
                actions.setDataTableQuery(getSurveyDataQuery(survey.name))
            }
            if (survey.targeting_flag?.filters?.groups) {
                actions.setTargetingFlagFilters(survey.targeting_flag.filters.groups)
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
            actions.setDataTableQuery(getSurveyDataQuery(survey.name))
            actions.loadSurveys()
            actions.reportSurveyLaunched(survey)
        },
        installSurveyPlugin: async (_, breakpoint) => {
            actions.setInstallingPlugin(true)
            actions.installPlugin('https://github.com/PostHog/feature-surveys', PluginInstallationType.Repository)
            await breakpoint(600)
            actions.setInstallingPlugin(false)
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
        targetingFlagFilters: [
            null as Pick<FeatureFlagFilters, 'groups'> | null,
            {
                setTargetingFlagFilters: (_, { groups }) => {
                    return { groups }
                },
                updateTargetingFlagFilters: (state, { index, properties }) => {
                    if (state?.groups) {
                        const groups = [...state.groups]
                        if (properties !== undefined) {
                            groups[index] = { ...groups[index], properties, rollout_percentage: 100 }
                        }
                        return { ...state, groups }
                    }
                    return state
                },
                removeConditionSet: (state, { index }) => {
                    const groups = [...(state?.groups || [])]
                    groups.splice(index, 1)
                    return { ...state, groups }
                },
                addConditionSet: (state) => {
                    if (state?.groups) {
                        const groups = [...state.groups, { properties: [], rollout_percentage: 0, variant: null }]
                        return { ...state, groups }
                    } else {
                        return {
                            groups: [{ properties: [], rollout_percentage: 0, variant: null }],
                        }
                    }
                },
            },
        ],
        dataTableQuery: [
            null as DataTableNode | null,
            {
                setDataTableQuery: (_, { query }) => query,
            },
        ],
        installingPlugin: [
            false,
            {
                setInstallingPlugin: (_, { installing }) => installing,
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
        propertySelectErrors: [
            (s) => [s.survey],
            (survey: NewSurvey) => {
                return survey.targeting_flag_filters?.groups?.map(({ properties }: FeatureFlagGroupType) => ({
                    properties: properties?.map((property: AnyPropertyFilter) => ({
                        value:
                            property.value === null ||
                            property.value === undefined ||
                            (Array.isArray(property.value) && property.value.length === 0)
                                ? "Property filters can't be empty"
                                : undefined,
                    })),
                }))
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
    }),
    forms(({ actions, props, values }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name, questions }) => ({
                name: !name && 'Please enter a name.',
                questions: questions.map(({ question }) => ({ question: !question && 'Please enter a question.' })),
            }),
            submit: async (surveyPayload) => {
                const surveyPayloadWithTargetingFlagFilters = {
                    ...surveyPayload,
                    ...(values.targetingFlagFilters ? { targeting_flag_filters: values.targetingFlagFilters } : {}),
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
