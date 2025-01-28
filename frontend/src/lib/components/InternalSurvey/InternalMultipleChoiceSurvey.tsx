/**
 * @fileoverview A component that displays an interactive survey within a session recording. It handles survey display, user responses, and submission
 */
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { InternalMultipleChoiceSurveyLogic } from 'lib/components/InternalSurvey/InternalMultipleChoiceSurveyLogic'

import { SurveyQuestion, SurveyQuestionType } from '~/types'

interface InternalSurveyProps {
    surveyId: string
}

export function InternalMultipleChoiceSurvey({ surveyId }: InternalSurveyProps): JSX.Element {
    const logic = InternalMultipleChoiceSurveyLogic({ surveyId })
    const { survey, surveyResponse, showThankYouMessage, thankYouMessage } = useValues(logic)
    const { handleChoiceChange, handleSurveyResponse } = useActions(logic)

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
                                {question.question}
                                {question.type === SurveyQuestionType.MultipleChoice && (
                                    <ul className="list-inside list-none my-2">
                                        {question.choices.map((choice) => (
                                            <li key={choice}>
                                                <LemonCheckbox
                                                    onChange={(checked) => handleChoiceChange(choice, checked)}
                                                    label={choice}
                                                />
                                            </li>
                                        ))}
                                    </ul>
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
