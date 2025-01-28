/**
 * @fileoverview A logic that handles the internal multiple choice survey
 */
import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import posthog, { Survey as PostHogSurvey } from 'posthog-js'

import type { InternalMultipleChoiceSurveyLogicType } from './InternalMultipleChoiceSurveyLogicType'

export interface InternalSurveyLogicProps {
    surveyId: string
}

export const InternalMultipleChoiceSurveyLogic = kea<InternalMultipleChoiceSurveyLogicType>([
    path(['lib', 'components', 'InternalSurvey', 'InternalMultipleChoiceSurveyLogic']),
    props({} as InternalSurveyLogicProps),
    key((props) => props.surveyId),
    actions({
        setSurveyId: (surveyId: string) => ({ surveyId }),
        getSurveys: () => ({}),
        setSurvey: (survey: PostHogSurvey) => ({ survey }),
        handleSurveys: (surveys: PostHogSurvey[]) => ({ surveys }),
        handleSurveyResponse: () => ({}),
        handleChoiceChange: (choice: string, isAdded: boolean) => ({ choice, isAdded }),
        setShowThankYouMessage: (showThankYouMessage: boolean) => ({ showThankYouMessage }),
        setThankYouMessage: (thankYouMessage: string) => ({ thankYouMessage }),
    }),
    reducers({
        surveyId: [
            null as string | null,
            {
                setSurveyId: (_, { surveyId }) => surveyId,
            },
        ],
        survey: [
            null as PostHogSurvey | null,
            {
                setSurvey: (_, { survey }) => survey,
            },
        ],
        thankYouMessage: [
            'Thank you for your feedback!',
            {
                setThankYouMessage: (_, { thankYouMessage }) => thankYouMessage,
            },
        ],
        showThankYouMessage: [
            false as boolean,
            {
                setShowThankYouMessage: (_, { showThankYouMessage }) => showThankYouMessage,
            },
        ],
        surveyResponse: [
            [] as string[],
            {
                handleChoiceChange: (state, { choice, isAdded }) =>
                    isAdded ? [...state, choice] : state.filter((c) => c !== choice),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        /** When surveyId is set, get the list of surveys for the user */
        setSurveyId: () => {
            posthog.getSurveys(actions.handleSurveys)
        },
        /** Callback for the surveys response. Filter it to the surveyId and set the survey */
        handleSurveys: ({ surveys }) => {
            const survey = surveys.find((s: PostHogSurvey) => s.id === values.surveyId)
            if (survey) {
                posthog.capture('survey shown', {
                    $survey_id: values.surveyId,
                })
                actions.setSurvey(survey)
                if (survey.appearance?.thankYouMessageHeader) {
                    actions.setThankYouMessage(survey.appearance?.thankYouMessageHeader)
                }
            }
        },
        /** When the survey response is sent, capture the response and show the thank you message */
        handleSurveyResponse: () => {
            posthog.capture('survey sent', {
                $survey_id: values.surveyId,
                $survey_response: values.surveyResponse,
            })
            actions.setShowThankYouMessage(true)
            setTimeout(() => actions.setSurvey(null), 5000)
        },
    })),
    afterMount(({ actions, props }) => {
        /** When the logic is mounted, set the surveyId from the props */
        actions.setSurveyId(props.surveyId)
    }),
])
