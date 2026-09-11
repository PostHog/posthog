import { useValues } from 'kea'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'

import { LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

import { Survey, SurveyQuestionBranchingType, SurveyType } from '~/types'

import { INTRO_SCREEN_PAGE_INDEX, NewSurvey } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { clampPreviewPageIndex } from './utils'

interface SurveyFormAppearanceProps {
    previewPageIndex: number
    survey: NewSurvey | Survey
    handleSetSelectedPageIndex: (activePreview: number) => void
    isEditingSurvey?: boolean
}

export function SurveyFormAppearance({
    previewPageIndex,
    survey,
    handleSetSelectedPageIndex,
}: SurveyFormAppearanceProps): JSX.Element | null {
    const { isAppearanceModalOpen } = useValues(surveysLogic)
    // A page index left on the intro after the toggle turns off falls back to question 0.
    const effectivePageIndex = clampPreviewPageIndex(previewPageIndex, survey)

    if (isAppearanceModalOpen) {
        return null
    }

    return survey.type !== SurveyType.API ? (
        <div className="flex flex-col h-full gap-2 items-start flex-1 xl:pl-8 pt-8 xl:pt-0">
            <SurveyAppearancePreview
                survey={survey as Survey}
                previewPageIndex={effectivePageIndex}
                onPreviewSubmit={(response) => {
                    // The intro screen is not a question, so getNextSurveyStep cannot resolve it:
                    // its button always advances to question 0.
                    if (effectivePageIndex === INTRO_SCREEN_PAGE_INDEX) {
                        handleSetSelectedPageIndex(0)
                        return
                    }
                    const nextStep = getNextSurveyStep(survey, effectivePageIndex, response)
                    if (nextStep === SurveyQuestionBranchingType.End && !survey.appearance?.displayThankYouMessage) {
                        return
                    }
                    handleSetSelectedPageIndex(
                        nextStep === SurveyQuestionBranchingType.End ? survey.questions.length : nextStep
                    )
                }}
                onPreviewBack={() =>
                    handleSetSelectedPageIndex(
                        Math.max(
                            survey.appearance?.displayIntroScreen ? INTRO_SCREEN_PAGE_INDEX : 0,
                            effectivePageIndex - 1
                        )
                    )
                }
            />
            <LemonField.Pure label="Current question" className="max-w-xs gap-1" htmlFor="current-question-select">
                <LemonSelect
                    onChange={(pageIndex) => handleSetSelectedPageIndex(pageIndex)}
                    id="current-question-select"
                    fullWidth
                    truncateText={{ maxWidthClass: 'max-w-60' }}
                    value={effectivePageIndex}
                    options={[
                        ...(survey.appearance?.displayIntroScreen
                            ? [
                                  {
                                      label: 'Intro screen',
                                      value: INTRO_SCREEN_PAGE_INDEX,
                                  },
                              ]
                            : []),
                        ...survey.questions.map((question, index) => ({
                            label: `${index + 1}. ${question.question ?? ''}`,
                            value: index,
                        })),
                        ...(survey.appearance?.displayThankYouMessage
                            ? [
                                  {
                                      label: `${survey.questions.length + 1}. Confirmation message`,
                                      value: survey.questions.length,
                                  },
                              ]
                            : []),
                    ]}
                />
            </LemonField.Pure>
        </div>
    ) : (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <SurveyAPIEditor survey={survey} />
        </div>
    )
}
