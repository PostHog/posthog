/**
 * @fileoverview A component that displays an interactive survey within a session recording. It handles survey display, user responses, and submission
 */
import { LemonButton, LemonCheckbox, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { internalMultipleChoiceSurveyLogic } from 'lib/components/InternalSurvey/internalMultipleChoiceSurveyLogic'

import { SurveyQuestion, SurveyQuestionType } from '~/types'

interface InternalSurveyProps {
    surveyId: string
}

export function InternalMultipleChoiceSurvey({ surveyId }: InternalSurveyProps): JSX.Element {
    const logic = internalMultipleChoiceSurveyLogic({ surveyId })
    const { survey, surveyResponse, showThankYouMessage, thankYouMessage, openChoice } = useValues(logic)
    const { handleChoiceChange, handleSurveyResponse, setOpenChoice } = useActions(logic)

    if (!survey) {
        return <></>
    }

    return (
        <div className="Popover Popover--padded Popover--appear-done Popover--enter-done my-4">
            <div className="Popover__box p-4">
                {survey.questions.map((question: SurveyQuestion) => (
                    <div key={question.question} className="text-sm">
                        {showThankYouMessage && thankYouMessage}
                        {!showThankYouMessage && (
                            <>
                                <strong>{question.question}</strong>
                                {question.type === SurveyQuestionType.MultipleChoice && (
                                    <ul className="list-inside list-none mt-2">
                                        {question.choices.map((choice) => (
                                            <li key={choice}>
                                                <LemonCheckbox
                                                    onChange={(checked) => handleChoiceChange(choice, checked)}
                                                    label={choice}
                                                    className="font-normal"
                                                />
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                {question.type === SurveyQuestionType.MultipleChoice && question.hasOpenChoice && (
                                    <div className="mt-2">
                                        Other:
                                        <LemonTextArea
                                            placeholder="Please share any additional comments or feedback"
                                            onChange={(value) => setOpenChoice(value)}
                                            value={openChoice ?? ''}
                                            className="my-2"
                                        />
                                    </div>
                                )}
                                <LemonButton
                                    type="primary"
                                    disabledReason={
                                        surveyResponse.length === 0 ? 'Please select at least one option' : false
                                    }
                                    onClick={handleSurveyResponse}
                                >
                                    {question.buttonText ?? 'Submit'}
                                </LemonButton>
                            </>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}
