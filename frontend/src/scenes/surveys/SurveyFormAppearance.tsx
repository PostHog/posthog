import { LemonSelect } from '@posthog/lemon-ui'

import { Survey, SurveyType } from '~/types'

import { defaultSurveyAppearance, NewSurvey } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearance, SurveyThankYou } from './SurveyAppearance'

interface SurveyFormAppearanceProps {
    activePreview: number
    survey: NewSurvey | Survey
    setActivePreview: (activePreview: number) => void
    isEditingSurvey?: boolean
}

export function SurveyFormAppearance({
    activePreview,
    survey,
    setActivePreview,
    isEditingSurvey,
}: SurveyFormAppearanceProps): JSX.Element {
    const showThankYou = survey.appearance?.displayThankYouMessage && activePreview >= survey.questions.length

    return survey.type !== SurveyType.API ? (
        <>
            {showThankYou ? (
                <SurveyThankYou appearance={survey.appearance} />
            ) : (
                <SurveyAppearance
                    surveyType={survey.type}
                    surveyQuestionItem={survey.questions[activePreview]}
                    appearance={{
                        ...(survey.appearance || defaultSurveyAppearance),
                        ...(survey.questions.length > 1 ? { submitButtonText: 'Next' } : null),
                    }}
                    isEditingSurvey={isEditingSurvey}
                />
            )}
            <LemonSelect
                onChange={(activePreview) => {
                    setActivePreview(activePreview)
                }}
                className="mt-4 whitespace-nowrap"
                fullWidth
                value={activePreview}
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
        </>
    ) : (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <SurveyAPIEditor survey={survey} />
        </div>
    )
}
