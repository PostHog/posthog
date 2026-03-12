import { connect, kea, key, path, props } from 'kea'
import { router, urlToAction } from 'kea-router'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { surveysLogic } from '../surveysLogic'
import type { surveyFormBuilderLogicType } from './surveyFormBuilderLogicType'

export interface SurveyFormBuilderLogicProps {
    id: string // 'new' for new surveys, or a UUID for editing
}

export const surveyFormBuilderLogic = kea<surveyFormBuilderLogicType>([
    path(['scenes', 'surveys', 'form', 'surveyFormBuilderLogic']),

    props({} as SurveyFormBuilderLogicProps),

    key((props) => props.id),

    connect(() => ({
        actions: [surveysLogic, ['loadSurveys'], eventUsageLogic, ['reportSurveyCreated', 'reportSurveyEdited']],
        values: [surveysLogic, ['formBuilderEnabled']],
    })),

    urlToAction(({ values, props }) => ({
        [urls.surveyFormBuilder(props.id)]: () => {
            if (!values.formBuilderEnabled) {
                router.actions.replace(urls.survey(props.id))
            }
        },
    })),
])
