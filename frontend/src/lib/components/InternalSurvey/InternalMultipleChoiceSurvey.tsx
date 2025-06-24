/**
 * @fileoverview A component that displays an interactive survey within a session recording. It handles survey display, user responses, and submission
 */
import { LemonButton, LemonCheckbox, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { SurveyQuestion, SurveyQuestionType } from '~/types'

import { internalMultipleChoiceSurveyLogic } from './internalMultipleChoiceSurveyLogic'

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
        <div className="Popover Popover--padded Popover--appear-done Popover--enter-done my-4 max-w-2xl">
            <div className="Popover__box p-4">
                {survey.questions.map((question: SurveyQuestion) => (
                    <div key={question.question} className="text-sm">
                        {showThankYouMessage && thankYouMessage}
                        {!showThankYouMessage && (
                            <>
                                <strong>{question.question}</strong>
                                {question.type === SurveyQuestionType.MultipleChoice && (
                                    <ul className="list-inside list-none mt-2">
                                        {question.choices.map((choice, index) => {
                                            // Add an open choice text area if the last choice is an open choice
                                            if (index === question.choices.length - 1 && question.hasOpenChoice) {
                                                return (
                                                    <div className="mt-2" key={choice}>
                                                        <LemonTextArea
                                                            placeholder="Please share any additional comments or feedback"
                                                            onChange={setOpenChoice}
                                                            value={openChoice ?? ''}
                                                            className="my-2"
                                                        />
                                                    </div>
                                                )
                                            }
                                            return (
                                                <li key={choice}>
                                                    <LemonCheckbox
                                                        onChange={(checked) => handleChoiceChange(choice, checked)}
                                                        label={choice}
                                                        className="font-normal"
                                                    />
                                                </li>
                                            )
                                        })}
                                    </ul>
                                )}
                                <LemonButton
                                    type="primary"
                                    disabledReason={
                                        surveyResponse.length === 0 && openChoice === null
                                            ? 'Please select at least one option'
                                            : false
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
