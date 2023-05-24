import { lemonToast } from '@posthog/lemon-ui'
import { kea, path, props, key, listeners, afterMount, reducers, actions, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { Breadcrumb, Survey, SurveyQuestionType, SurveyType } from '~/types'
import type { surveyLogicType } from './surveyLogicType'
import { DataTableNode, NodeKind } from '~/queries/schema'

export interface NewSurvey
    extends Pick<Survey, 'name' | 'description' | 'type' | 'questions' | 'targeting_flag' | 'start_date' | 'end_date'> {
    linked_flag_id: number | undefined
}

const NEW_SURVEY: NewSurvey = {
    name: '',
    description: '',
    questions: [{ type: SurveyQuestionType.Open, question: '' }],
    type: SurveyType.Popover,
    linked_flag_id: undefined,
    targeting_flag: null,
    start_date: null,
    end_date: null,
}

export interface SurveyLogicProps {
    id: string | 'new'
}

const DEFAULT_DATATABLE_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', 'event', 'timestamp', 'person'],
        orderBy: ['timestamp DESC'],
        after: '-30d',
        limit: 100,
        event: 'insight viewed',
    },
    propertiesViaUrl: true,
    showExport: true,
    showReload: true,
    showColumnConfigurator: true,
    showEventFilter: true,
    showPropertyFilter: true,
}

export const surveyLogic = kea<surveyLogicType>([
    path(['scenes', 'surveys', 'surveyLogic']),
    props({} as SurveyLogicProps),
    key(({ id }) => id),
    actions({
        editingSurvey: (editing: boolean) => ({ editing }),
    }),
    loaders(({ props }) => ({
        survey: {
            loadSurvey: async () => {
                if (props.id && props.id !== 'new') {
                    return await api.surveys.get(props.id)
                    // return await ({ id: '123', name: 'early access', created_at: new Date() } as Survey)
                }
                return { ...NEW_SURVEY }
            },
            createSurvey: async (surveyPayload) => {
                return await api.surveys.create(surveyPayload)
            },
            updateSurvey: async (surveyPayload) => {
                return await api.surveys.update(props.id, surveyPayload)
            },
        },
    })),
    listeners(() => ({
        createSurveySuccess: async ({ survey }) => {
            lemonToast.success(<>Survey {survey.name} created</>)
            router.actions.push(urls.survey(survey.id))
        },
        updateSurveySuccess: async ({ survey }) => {
            lemonToast.success(<>Survey {survey.name} updated</>)
            router.actions.push(urls.survey(survey.id))
        },
    })),
    reducers({
        isEditingSurvey: [
            false,
            {
                editingSurvey: (_, { editing }) => editing,
            },
        ],
        dataTableQuery: [DEFAULT_DATATABLE_QUERY as DataTableNode],
    }),
    selectors({
        isSurveyRunning: [
            (s) => [s.survey],
            (survey): boolean => {
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
    }),
    forms(({ actions, props }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name }) => ({
                name: !name ? 'Please enter a name' : undefined,
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
