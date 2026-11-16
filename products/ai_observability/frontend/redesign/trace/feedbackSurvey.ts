import { dayjs } from 'lib/dayjs'
import { SURVEY_RATING_SCALE } from 'scenes/surveys/constants'

import { Survey, SurveyQuestion, SurveyQuestionBranchingType, SurveyQuestionType, SurveyType } from '~/types'

export const DEFAULT_FEEDBACK_SURVEY_NAME = 'AI response feedback'
export const DEFAULT_FEEDBACK_SURVEY_QUESTION = 'Was this response helpful?'
export const DEFAULT_FEEDBACK_FOLLOW_UP_QUESTION = 'What went wrong?'

export interface FeedbackSurveyFormValues {
    name: string
    followUpEnabled: boolean
    followUpQuestion: string
}

/**
 * Builds the survey `useThumbSurvey` expects: an API survey whose first question is a 1-2 (thumbs up/down) rating
 * that submits on selection. The optional follow-up is only shown after a thumbs down.
 *
 * The survey is launched right away. An API survey never displays on its own, and the SDK only loads surveys that
 * have started, so a draft would make the hook do nothing.
 */
export function buildFeedbackSurveyPayload(values: FeedbackSurveyFormValues): Partial<Survey> {
    const withFollowUp = values.followUpEnabled && values.followUpQuestion.trim().length > 0

    const questions: SurveyQuestion[] = [
        {
            type: SurveyQuestionType.Rating,
            question: DEFAULT_FEEDBACK_SURVEY_QUESTION,
            display: 'emoji',
            scale: SURVEY_RATING_SCALE.THUMB_2_POINT,
            lowerBoundLabel: 'Not helpful',
            upperBoundLabel: 'Helpful',
            skipSubmitButton: true,
            optional: false,
            // A thumbs up ends the survey, so only a thumbs down reaches the follow-up.
            ...(withFollowUp
                ? {
                      branching: {
                          type: SurveyQuestionBranchingType.ResponseBased,
                          responseValues: { positive: SurveyQuestionBranchingType.End },
                      },
                  }
                : {}),
        },
    ]

    if (withFollowUp) {
        questions.push({
            type: SurveyQuestionType.Open,
            question: values.followUpQuestion.trim(),
            optional: true,
        })
    }

    return {
        name: values.name.trim(),
        type: SurveyType.API,
        questions,
        start_date: dayjs().toISOString(),
    }
}

export function buildThumbSurveySnippet(surveyId: string): string {
    return `import { useThumbSurvey } from 'posthog-js/react/surveys'

function AIResponseFeedback({ traceId }: { traceId: string }) {
    const { respond, triggerRef } = useThumbSurvey({
        surveyId: '${surveyId}',
        // Links each response to the trace, so it shows on the trace's Feedback tab.
        properties: { $ai_trace_id: traceId },
    })

    return (
        <div ref={triggerRef}>
            <button onClick={() => respond('up')}>👍</button>
            <button onClick={() => respond('down')}>👎</button>
        </div>
    )
}`
}
