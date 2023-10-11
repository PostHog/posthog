import { actions, kea, path } from 'kea'
import { surveyTemplatesLogicType } from './surveyTemplatesLogicType'
import { actionToUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'

export const surveyTemplatesLogic = kea<surveyTemplatesLogicType>([
    path(['scenes', 'surveys', 'surveyTemplatesLogic']),
    actions({
        openSurveyTemplate: (template: any) => ({ template }),
    }),
    actionToUrl({
        openSurveyTemplate: () => {
            router.actions.push(urls.survey('new'))
        },
    }),
])
