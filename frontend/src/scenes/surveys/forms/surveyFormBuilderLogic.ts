import { connect, kea, key, path, props, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { surveyLogic } from '../surveyLogic'
import { surveysLogic } from '../surveysLogic'
import type { surveyFormBuilderLogicType } from './surveyFormBuilderLogicType'

export interface SurveyFormBuilderLogicProps {
    id: string // 'new' for new surveys, or a UUID for editing
}

export const surveyFormBuilderLogic = kea<surveyFormBuilderLogicType>([
    path(['scenes', 'surveys', 'form', 'surveyFormBuilderLogic']),

    props({} as SurveyFormBuilderLogicProps),

    key((props) => props.id),

    connect((props: SurveyFormBuilderLogicProps) => ({
        actions: [
            surveyLogic({ id: props.id }),
            ['setSurveyValue', 'resetSurvey', 'loadSurvey'],
            surveysLogic,
            ['loadSurveys'],
            eventUsageLogic,
            ['reportSurveyCreated', 'reportSurveyEdited'],
        ],
        values: [surveyLogic({ id: props.id }), ['survey', 'surveyLoading'], featureFlagLogic, ['featureFlags']],
    })),

    selectors({
        formBuilderEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.SURVEYS_FORM_BUILDER],
        ],
    }),

    urlToAction(({ values, props }) => ({
        [urls.surveyFormBuilder(props.id)]: () => {
            if (!values.formBuilderEnabled) {
                router.actions.replace(urls.survey(props.id))
            }
        },
    })),
])
