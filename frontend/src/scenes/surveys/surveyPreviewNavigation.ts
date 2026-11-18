import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'

import { Survey, SurveyQuestionBranchingType } from '~/types'

import { INTRO_SCREEN_PAGE_INDEX, NewSurvey } from './constants'

/** The page to show after a preview submit, or null to stay on the current one. */
export function getNextPreviewPageIndex(
    survey: Survey | NewSurvey,
    pageIndex: number,
    response: string | string[] | number | null
): number | null {
    // The intro is not a question, so getNextSurveyStep cannot resolve it.
    if (pageIndex === INTRO_SCREEN_PAGE_INDEX) {
        return 0
    }
    const nextStep = getNextSurveyStep(survey, pageIndex, response)
    if (nextStep !== SurveyQuestionBranchingType.End) {
        return nextStep
    }
    return survey.appearance?.displayThankYouMessage ? survey.questions.length : null
}
