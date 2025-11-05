import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { Survey } from '~/types'

import type { internalMultipleChoiceSurveyLogicType } from './internalMultipleChoiceSurveyLogicType'

export interface InternalSurveyLogicProps {
    surveyId: string
}

export const internalMultipleChoiceSurveyLogic = kea<internalMultipleChoiceSurveyLogicType>([
    path(['lib', 'components', 'InternalSurvey', 'internalMultipleChoiceSurveyLogicType']),
    props({} as InternalSurveyLogicProps),
    key((props) => props.surveyId),
    actions({
        getSurveys: () => ({}),
        setSurvey: (survey: Survey) => ({ survey }),
        handleSurveys: (surveys: Survey[]) => ({ surveys }),
        handleSurveyResponse: () => ({}),
        handleChoiceChange: (choice: string, isAdded: boolean) => ({ choice, isAdded }),
        setShowThankYouMessage: (showThankYouMessage: boolean) => ({ showThankYouMessage }),
        setThankYouMessage: (thankYouMessage: string) => ({ thankYouMessage }),
        setOpenChoice: (openChoice: string) => ({ openChoice }),
    }),
    reducers({
        survey: [
            null as Survey | null,
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
        openChoice: [
            null as string | null,
            {
                setOpenChoice: (_, { openChoice }) => openChoice,
            },
        ],
        surveyResponse: [
            [] as string[],
            {
                handleChoiceChange: (state, { choice, isAdded }) =>
                    isAdded ? [...state, choice] : state.filter((c: string) => c !== choice),
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        /** When surveyId is set, get the list of surveys for the user */
        setSurveyId: () => {},
        /** Callback for the surveys response. Filter it to the surveyId and set the survey */
        handleSurveys: ({ surveys }) => {
            const survey = surveys.find((s: Survey) => s.id === props.surveyId)
            if (survey) {
                posthog.capture('survey shown', {
                    $survey_id: props.surveyId,
                })
                actions.setSurvey(survey)

                if (survey.appearance?.thankYouMessageHeader) {
                    actions.setThankYouMessage(survey.appearance?.thankYouMessageHeader)
                }
            }
        },
        /** When the survey response is sent, capture the response and show the thank you message */
        handleSurveyResponse: () => {
            const payload = {
                $survey_id: props.surveyId,
                $survey_response: values.surveyResponse,
            }
            if (values.openChoice) {
                payload.$survey_response.push(values.openChoice)
            }
            posthog.capture('survey sent', payload)

            actions.setShowThankYouMessage(true)
            setTimeout(() => actions.setSurvey(null as unknown as Survey), 5000)
        },
    })),
    afterMount(({ actions }) => {
        /** When the logic is mounted, set the surveyId from the props */
        posthog.getSurveys((surveys) => actions.handleSurveys(surveys as unknown as Survey[]))
    }),
])
