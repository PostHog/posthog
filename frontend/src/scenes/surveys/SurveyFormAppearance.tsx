import { LemonSelect } from '@posthog/lemon-ui'
import { SurveyAppearance, SurveyThankYou } from './SurveyAppearance'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { NewSurvey, defaultSurveyAppearance } from './constants'
import { LinkSurveyQuestion, Survey, SurveyQuestionType, SurveyType } from '~/types'

interface SurveyFormAppearanceProps {
    activePreview: number
    survey: NewSurvey | Survey
    setActivePreview: (activePreview: number) => void
}

export function SurveyFormAppearance({
    activePreview,
    survey,
    setActivePreview,
}: SurveyFormAppearanceProps): JSX.Element {
    const showThankYou = survey.appearance.displayThankYouMessage && activePreview >= survey.questions.length

    return (
        <div className="SurveyFormAppearance">
            {survey.type !== SurveyType.API ? (
                <>
                    {showThankYou ? (
                        <SurveyThankYou appearance={survey.appearance} />
                    ) : (
                        <SurveyAppearance
                            type={survey.questions[activePreview].type}
                            surveyQuestionItem={survey.questions[activePreview]}
                            question={survey.questions[activePreview].question}
                            description={survey.questions[activePreview].description}
                            link={
                                survey.questions[activePreview].type === SurveyQuestionType.Link
                                    ? (survey.questions[activePreview] as LinkSurveyQuestion).link
                                    : undefined
                            }
                            appearance={{
                                ...(survey.appearance || defaultSurveyAppearance),
                                ...(survey.questions.length > 1 ? { submitButtonText: 'Next' } : null),
                            }}
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
                            ...(survey.appearance.displayThankYouMessage
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
            )}
        </div>
    )
}
