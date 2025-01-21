import { LemonSelect } from '@posthog/lemon-ui'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'

import { Survey, SurveyQuestionBranchingType, SurveyType } from '~/types'

import { NewSurvey } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'

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
}: SurveyFormAppearanceProps): JSX.Element {
    return survey.type !== SurveyType.API ? (
        <div className="survey-view max-w-72">
            <SurveyAppearancePreview
                survey={survey as Survey}
                previewPageIndex={previewPageIndex}
                onPreviewSubmit={(response) => {
                    const nextStep = getNextSurveyStep(survey, previewPageIndex, response)
                    handleSetSelectedPageIndex(
                        nextStep === SurveyQuestionBranchingType.End ? survey.questions.length : nextStep
                    )
                }}
            />
            <LemonSelect
                onChange={(pageIndex) => handleSetSelectedPageIndex(pageIndex)}
                className="mt-4 whitespace-nowrap"
                fullWidth
                value={previewPageIndex}
                options={[
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
        </div>
    ) : (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <SurveyAPIEditor survey={survey} />
        </div>
    )
}
