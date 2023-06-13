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
    Survey,
    SurveyQuestionType,
    SurveyType,
} from '~/types'
import type { surveyLogicType } from './surveyLogicType'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { surveysLogic } from './surveysLogic'
import { dayjs } from 'lib/dayjs'

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

export interface SurveyLogicProps {
    id: string | 'new'
}

export const surveyLogic = kea<surveyLogicType>([
    path(['scenes', 'surveys', 'surveyLogic']),
    props({} as SurveyLogicProps),
    key(({ id }) => id),
    connect(() => ({
        actions: [surveysLogic, ['loadSurveys']],
    })),
    actions({
        editingSurvey: (editing: boolean) => ({ editing }),
        updateTargetingFlagFilters: (index: number, properties: AnyPropertyFilter[]) => ({ index, properties }),
        addConditionSet: true,
        removeConditionSet: (index: number) => ({ index }),
        launchSurvey: true,
        stopSurvey: true,
        archiveSurvey: true,
        setDataTableQuery: (query: DataTableNode) => ({ query }),
    }),
    loaders(({ props, values }) => ({
        survey: {
            loadSurvey: async () => {
                if (props.id && props.id !== 'new') {
                    return await api.surveys.get(props.id)
                }
                return { ...NEW_SURVEY }
            },
            createSurvey: async (surveyPayload) => {
                return await api.surveys.create(surveyPayload)
            },
            updateSurvey: async (surveyPayload) => {
                return await api.surveys.update(props.id, surveyPayload)
            },
            updateTargetingFlagFilters: ({ index, properties }) => {
                if (!values.survey.targeting_flag_filters) {
                    return values.survey
                }
                const surv = { ...values.survey }
                const groups = [...values.survey.targeting_flag_filters.groups]
                if (properties !== undefined) {
                    groups[index] = { ...groups[index], properties, rollout_percentage: 100 }
                }
                return { ...surv, targeting_flag_filters: { groups } }
            },
            removeConditionSet: ({ index }) => {
                if (!values.survey) {
                    return values.survey
                }
                const groups = [...(values.survey.targeting_flag_filters?.groups || [])]
                groups.splice(index, 1)
                return { ...values.survey, targeting_flag_filters: { ...values.survey.targeting_flag_filters, groups } }
            },
            addConditionSet: () => {
                if (!values.survey) {
                    return values.survey
                }
                if (values.survey.targeting_flag_filters) {
                    const groups = [
                        ...values.survey?.targeting_flag_filters?.groups,
                        { properties: [], rollout_percentage: 0, variant: null },
                    ]
                    return {
                        ...values.survey,
                        targeting_flag_filters: { ...values.survey?.targeting_flag_filters, groups },
                    }
                } else {
                    return {
                        ...values.survey,
                        targeting_flag_filters: {
                            groups: [{ properties: [], rollout_percentage: 0, variant: null }],
                        },
                    }
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        loadSurveySuccess: ({ survey }) => {
            if (survey.start_date) {
                const surveyDataQuery: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: ['*', 'event', 'timestamp', 'person'],
                        orderBy: ['timestamp DESC'],
                        after: '-30d',
                        limit: 100,
                        event: getSurveyEventName(survey.name),
                    },
                    propertiesViaUrl: true,
                    showExport: true,
                    showReload: true,
                    showColumnConfigurator: true,
                    showEventFilter: true,
                    showPropertyFilter: true,
                }
                actions.setDataTableQuery(surveyDataQuery)
            }
        },
        createSurveySuccess: async ({ survey }) => {
            lemonToast.success(<>Survey {survey.name} created</>)
            actions.loadSurveys()
            router.actions.replace(urls.survey(survey.id))
        },
        updateSurveySuccess: async ({ survey }) => {
            lemonToast.success(<>Survey {survey.name} updated</>)
            actions.editingSurvey(false)
            router.actions.replace(urls.survey(survey.id))
        },
        launchSurvey: async () => {
            const startDate = dayjs()
            actions.updateSurvey({ start_date: startDate.toISOString() })
        },
        stopSurvey: async () => {
            const endDate = dayjs()
            actions.updateSurvey({ end_date: endDate.toISOString() })
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
    }),
    forms(({ actions, props }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name, questions }) => ({
                name: !name && 'Please enter a name.',
                questions: questions.map(({ question }) => ({ question: !question && 'Please enter a question.' })),
            }),
            submit: async (surveyPayload) => {
                if (props.id && props.id !== 'new') {
                    actions.updateSurvey(surveyPayload)
                } else {
                    actions.createSurvey(surveyPayload)
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
