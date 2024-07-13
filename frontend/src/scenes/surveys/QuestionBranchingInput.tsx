import './EditSurvey.scss'

import { LemonDialog, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { truncate } from 'lib/utils'

import { MultipleSurveyQuestion, RatingSurveyQuestion, SurveyQuestionBranchingType, SurveyQuestionType } from '~/types'

import { surveyLogic } from './surveyLogic'

export function QuestionBranchingInput({
    questionIndex,
    question,
}: {
    questionIndex: number
    question: RatingSurveyQuestion | MultipleSurveyQuestion
}): JSX.Element {
    const { survey, getBranchingDropdownValue } = useValues(surveyLogic)
    const { setQuestionBranchingType, setSurveyValue } = useActions(surveyLogic)

    const availableNextQuestions = survey.questions
        .map((question, questionIndex) => ({
            ...question,
            questionIndex,
        }))
        .filter((_, idx) => questionIndex !== idx)
    const branchingDropdownValue = getBranchingDropdownValue(questionIndex, question)
    const hasResponseBasedBranching =
        question.type === SurveyQuestionType.Rating || question.type === SurveyQuestionType.SingleChoice

    return (
        <>
            <LemonField name="branching" label="After this question, go to:" className="max-w-80">
                <LemonSelect
                    className="max-w-80 whitespace-nowrap"
                    value={branchingDropdownValue}
                    data-attr={`survey-question-${questionIndex}-branching-select`}
                    onSelect={(type) => {
                        const handleSelect = (): void => {
                            let specificQuestionIndex
                            if (type.startsWith(SurveyQuestionBranchingType.SpecificQuestion)) {
                                specificQuestionIndex = parseInt(type.split(':')[1])
                                type = SurveyQuestionBranchingType.SpecificQuestion
                            }
                            setQuestionBranchingType(questionIndex, type, specificQuestionIndex)
                        }

                        if (survey.appearance && survey.appearance.shuffleQuestions) {
                            LemonDialog.open({
                                title: 'Your survey has question shuffling enabled',
                                description: (
                                    <p className="py-2">
                                        Adding branching logic will disable shuffling of questions. Are you sure you
                                        want to continue?
                                    </p>
                                ),
                                primaryButton: {
                                    children: 'Continue',
                                    status: 'danger',
                                    onClick: () => {
                                        setSurveyValue('appearance', { ...survey.appearance, shuffleQuestions: false })
                                        handleSelect()
                                    },
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        } else {
                            handleSelect()
                        }
                    }}
                    options={[
                        ...(questionIndex < survey.questions.length - 1
                            ? [
                                  {
                                      label: 'Next question',
                                      value: SurveyQuestionBranchingType.NextQuestion,
                                  },
                              ]
                            : []),
                        {
                            label: survey.appearance?.displayThankYouMessage ? 'Confirmation message' : 'End',
                            value: SurveyQuestionBranchingType.End,
                        },
                        ...(hasResponseBasedBranching
                            ? [
                                  {
                                      label: 'Specific question based on answer',
                                      value: SurveyQuestionBranchingType.ResponseBased,
                                  },
                              ]
                            : []),
                        ...availableNextQuestions.map((question) => ({
                            label: truncate(`${question.questionIndex + 1}. ${question.question}`, 40),
                            value: `${SurveyQuestionBranchingType.SpecificQuestion}:${question.questionIndex}`,
                        })),
                    ]}
                />
            </LemonField>
            {branchingDropdownValue === SurveyQuestionBranchingType.ResponseBased && (
                <QuestionResponseBasedBranchingInput question={question} questionIndex={questionIndex} />
            )}
        </>
    )
}

function QuestionResponseBasedBranchingInput({
    questionIndex,
    question,
}: {
    questionIndex: number
    question: RatingSurveyQuestion | MultipleSurveyQuestion
}): JSX.Element {
    const { survey, getResponseBasedBranchingDropdownValue } = useValues(surveyLogic)
    const { setResponseBasedBranchingForQuestion } = useActions(surveyLogic)

    const availableNextQuestions = survey.questions
        .map((question, questionIndex) => ({
            ...question,
            questionIndex,
        }))
        .filter((_, idx) => questionIndex !== idx)

    let config: { value: string | number; label: string }[] = []

    if (question.type === SurveyQuestionType.Rating && question.scale === 3) {
        config = [
            { value: 'negative', label: '1 (Negative)' },
            { value: 'neutral', label: '2 (Neutral)' },
            { value: 'positive', label: '3 (Positive)' },
        ]
    } else if (question.type === SurveyQuestionType.Rating && question.scale === 5) {
        config = [
            { value: 'negative', label: '1 to 2 (Negative)' },
            { value: 'neutral', label: '3 (Neutral)' },
            { value: 'positive', label: '4 to 5 (Positive)' },
        ]
    } else if (question.type === SurveyQuestionType.Rating && question.scale === 10) {
        config = [
            // NPS categories
            { value: 'detractors', label: '0 to 6 (Detractors)' },
            { value: 'passives', label: '7 to 8 (Passives)' },
            { value: 'promoters', label: '9 to 10 (Promoters)' },
        ]
    } else if (question.type === SurveyQuestionType.SingleChoice) {
        config = question.choices.map((choice, choiceIndex) => ({
            value: choiceIndex,
            label: `Option ${choiceIndex + 1} ("${truncate(choice, 15)}")`,
        }))
    }

    return (
        <div className="mt-2 space-y-2">
            {config.map(({ value, label }, i) => (
                <div key={i} className="flex">
                    <div className="w-2/3 flex items-center">
                        <div>
                            If the answer is<span className="font-bold">&nbsp;{label}</span>, go to:
                        </div>
                    </div>
                    <div className="w-1/3 flex justify-end">
                        <LemonSelect
                            className="w-full whitespace-nowrap"
                            value={getResponseBasedBranchingDropdownValue(questionIndex, question, value)}
                            data-attr={`survey-question-${questionIndex}-branching-response_based-select-${i}`}
                            onSelect={(nextStep) => {
                                let specificQuestionIndex
                                if (nextStep.startsWith(SurveyQuestionBranchingType.SpecificQuestion)) {
                                    specificQuestionIndex = parseInt(nextStep.split(':')[1])
                                    nextStep = SurveyQuestionBranchingType.SpecificQuestion
                                }
                                setResponseBasedBranchingForQuestion(
                                    questionIndex,
                                    value,
                                    nextStep,
                                    specificQuestionIndex
                                )
                            }}
                            options={[
                                ...(questionIndex < survey.questions.length - 1
                                    ? [
                                          {
                                              label: 'Next question',
                                              value: SurveyQuestionBranchingType.NextQuestion,
                                          },
                                      ]
                                    : []),
                                {
                                    label: 'Confirmation message',
                                    value: SurveyQuestionBranchingType.End,
                                },
                                ...availableNextQuestions.map((question) => ({
                                    label: truncate(`${question.questionIndex + 1}. ${question.question}`, 28),
                                    value: `${SurveyQuestionBranchingType.SpecificQuestion}:${question.questionIndex}`,
                                })),
                            ]}
                        />
                    </div>
                </div>
            ))}
        </div>
    )
}
