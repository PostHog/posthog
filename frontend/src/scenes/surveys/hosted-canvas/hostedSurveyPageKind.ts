import { Survey } from '~/types'

import { INTRO_SCREEN_PAGE_INDEX, NewSurvey } from '../constants'

export type HostedSurveyPageKind = 'intro' | 'question' | 'confirmation'

export function getHostedSurveyPageKind(survey: Survey | NewSurvey, pageIndex: number): HostedSurveyPageKind {
    if (survey.appearance?.displayIntroScreen && pageIndex === INTRO_SCREEN_PAGE_INDEX) {
        return 'intro'
    }
    if (survey.appearance?.displayThankYouMessage && pageIndex === survey.questions.length) {
        return 'confirmation'
    }
    return 'question'
}
