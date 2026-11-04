import { SurveyAppearance, SurveyQuestionDescriptionContentType } from '~/types'

export function isIntroScreenShown(appearance?: SurveyAppearance | null): boolean {
    return !!appearance?.displayIntroScreen && !!(appearance.introScreenHeader || appearance.introScreenDescription)
}

export function getIntroScreenDescriptionContentType(
    appearance?: SurveyAppearance | null
): SurveyQuestionDescriptionContentType {
    return appearance?.introScreenDescriptionContentType ?? 'html'
}
