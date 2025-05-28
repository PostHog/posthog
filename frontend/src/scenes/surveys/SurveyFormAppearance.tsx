import { LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

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
    const { isAppearanceModalOpen } = useValues(surveyLogic)

    if (isAppearanceModalOpen) {
        return <div />
    }

    return survey.type !== SurveyType.API ? (
        <div className="flex flex-col gap-2 pr-4">
            <SurveyAppearancePreview
                survey={survey as Survey}
                previewPageIndex={previewPageIndex}
                onPreviewSubmit={(response) => {
                    const nextStep = getNextSurveyStep(survey, previewPageIndex, response)
                    if (nextStep === SurveyQuestionBranchingType.End && !survey.appearance?.displayThankYouMessage) {
                        return
                    }
                    handleSetSelectedPageIndex(
                        nextStep === SurveyQuestionBranchingType.End ? survey.questions.length : nextStep
                    )
                }}
            />
            <LemonField.Pure label="Current question" className="max-w-xs gap-1" htmlFor="current-question-select">
                <LemonSelect
                    onChange={(pageIndex) => handleSetSelectedPageIndex(pageIndex)}
                    className="whitespace-nowrap"
                    id="current-question-select"
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
            </LemonField.Pure>
        </div>
    ) : (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <SurveyAPIEditor survey={survey} />
        </div>
    )
}
