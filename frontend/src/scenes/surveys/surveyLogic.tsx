import { lemonToast } from '@posthog/lemon-ui'
import { kea, path, props, key, listeners, afterMount, reducers, actions } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { Survey, SurveyType } from '~/types'
import type { surveyLogicType } from './surveyLogicType'

type NewSurvey = Pick<Survey, 'name' | 'description' | 'type' | 'linked_flag' | 'questions'>

const NEW_SURVEY: NewSurvey = {
    name: '',
    description: '',
    questions: [],
    type: SurveyType.Popover,
    linked_flag: null,
}

export interface SurveyLogicProps {
    id: string | 'new'
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
    }),
    forms(({ actions, values }) => ({
        survey: {
            defaults: { ...NEW_SURVEY } as NewSurvey | Survey,
            errors: ({ name }) => ({
                name: !name ? 'Please enter a name' : undefined,
            }),
            submit: async (surveyPayload) => {
                if (values.survey?.id) {
                    actions.updateSurvey(surveyPayload)
                } else {
                    actions.createSurvey(surveyPayload)
                }
                actions.loadSurveySuccess(surveyPayload)
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
