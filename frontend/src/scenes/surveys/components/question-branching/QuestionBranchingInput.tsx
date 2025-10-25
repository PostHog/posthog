import { useActions, useValues } from 'kea'

import { LemonDialog, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { truncate } from 'lib/utils'
import { NPS_DETRACTOR_LABEL, NPS_PASSIVE_LABEL, NPS_PROMOTER_LABEL } from 'scenes/surveys/constants'

import {
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestion,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
} from '~/types'

import { surveyLogic } from '../../surveyLogic'
import {
    canQuestionHaveResponseBasedBranching,
    createSpecificQuestionValue,
    dropdownValueToBranchingConfig,
} from './utils'

function getAvailableQuestionOptions(
    allQuestions: SurveyQuestion[],
    currentQuestionIndex: number,
    maxLabelLength = 40
): { label: string; value: string }[] {
    return allQuestions
        .map((question, questionIndex) => ({
            ...question,
            questionIndex,
        }))
        .filter((_, idx) => currentQuestionIndex !== idx) // Exclude current question
        .map((question) => ({
            label: truncate(`${question.questionIndex + 1}. ${question.question}`, maxLabelLength),
            value: createSpecificQuestionValue(question.questionIndex),
        }))
}

export function QuestionBranchingInput({
    questionIndex,
    question,
}: {
    questionIndex: number
    question: SurveyQuestion
}): JSX.Element {
    const { survey, getBranchingDropdownValue } = useValues(surveyLogic)
    const { setQuestionBranchingType, setSurveyValue } = useActions(surveyLogic)

    const availableQuestions = getAvailableQuestionOptions(survey.questions, questionIndex)
    const branchingDropdownValue = getBranchingDropdownValue(questionIndex, question)
    const hasResponseBasedBranching = canQuestionHaveResponseBasedBranching(question)
    const isLastQuestion = questionIndex >= survey.questions.length - 1

    // Build dropdown options based on available branching types
    const dropdownOptions = [
        // "Next question" option (only if not the last question)
        ...(!isLastQuestion
            ? [
                  {
                      label: 'Next question',
                      value: SurveyQuestionBranchingType.NextQuestion,
                  },
              ]
            : []),

        // "End" option (shows different label based on thank you message setting)
        {
            label: survey.appearance?.displayThankYouMessage ? 'Confirmation message' : 'End',
            value: SurveyQuestionBranchingType.End,
        },

        // "Response-based" option (only for rating/single choice questions)
        ...(hasResponseBasedBranching
            ? [
                  {
                      label: 'Specific question based on answer',
                      value: SurveyQuestionBranchingType.ResponseBased,
                  },
              ]
            : []),

        // Individual question options
        ...availableQuestions,
    ]

    function handleBranchingSelection(selectedValue: string): void {
        const handleSelect = (): void => {
            const { type: branchingType, specificQuestionIndex } = dropdownValueToBranchingConfig(selectedValue)
            setQuestionBranchingType(questionIndex, branchingType, specificQuestionIndex)
        }

        // Show warning if shuffle is enabled and user is adding branching logic
        if (survey.appearance?.shuffleQuestions) {
            LemonDialog.open({
                title: 'Your survey has question shuffling enabled',
                description: (
                    <p className="py-2">
                        Adding branching logic will disable shuffling of questions. Are you sure you want to continue?
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
    }

    return (
        <>
            <LemonField name="branching" label="After this question, go to:" className="max-w-80">
                <LemonSelect
                    className="max-w-80 whitespace-nowrap"
                    value={branchingDropdownValue}
                    data-attr={`survey-question-${questionIndex}-branching-select`}
                    onSelect={handleBranchingSelection}
                    options={dropdownOptions}
                />
            </LemonField>
            {/* Show response-based branching UI when that option is selected */}
            {branchingDropdownValue === SurveyQuestionBranchingType.ResponseBased && hasResponseBasedBranching && (
                <QuestionResponseBasedBranchingInput question={question} questionIndex={questionIndex} />
            )}
        </>
    )
}

function getResponseConfiguration(
    question: RatingSurveyQuestion | MultipleSurveyQuestion
): { value: string | number; label: string }[] {
    if (question.type === SurveyQuestionType.Rating) {
        // Handle different rating scales with appropriate groupings
        switch (question.scale) {
            case 3:
                return [
                    { value: 'negative', label: '1 (Negative)' },
                    { value: 'neutral', label: '2 (Neutral)' },
                    { value: 'positive', label: '3 (Positive)' },
                ]
            case 5:
                return [
                    { value: 'negative', label: '1 to 2 (Negative)' },
                    { value: 'neutral', label: '3 (Neutral)' },
                    { value: 'positive', label: '4 to 5 (Positive)' },
                ]
            case 7:
                return [
                    { value: 'negative', label: '1 to 3 (Negative)' },
                    { value: 'neutral', label: '4 (Neutral)' },
                    { value: 'positive', label: '5 to 7 (Positive)' },
                ]
            case 10:
                // NPS scale with standard categories
                return [
                    { value: 'detractors', label: `0 to 6 (${NPS_DETRACTOR_LABEL})` },
                    { value: 'passives', label: `7 to 8 (${NPS_PASSIVE_LABEL})` },
                    { value: 'promoters', label: `9 to 10 (${NPS_PROMOTER_LABEL})` },
                ]
            default:
                return []
        }
    } else if (question.type === SurveyQuestionType.SingleChoice) {
        // Map each choice to its index for branching
        return question.choices.map((choice, choiceIndex) => ({
            value: choiceIndex,
            label: `Option ${choiceIndex + 1} ("${truncate(choice, 15)}")`,
        }))
    }

    return []
}

function QuestionResponseBasedBranchingInput({
    questionIndex,
    question,
}: {
    questionIndex: number
    question: RatingSurveyQuestion | MultipleSurveyQuestion
}): JSX.Element | null {
    const { survey, getResponseBasedBranchingDropdownValue } = useValues(surveyLogic)
    const { setResponseBasedBranchingForQuestion } = useActions(surveyLogic)

    const availableQuestions = getAvailableQuestionOptions(survey.questions, questionIndex, 28)
    const responseConfig = getResponseConfiguration(question)
    const isLastQuestion = questionIndex >= survey.questions.length - 1

    if (responseConfig.length === 0) {
        return null
    }

    // Build dropdown options for response-based branching destinations
    const responseDestinationOptions = [
        // "Next question" option (only if not the last question)
        ...(!isLastQuestion
            ? [
                  {
                      label: 'Next question',
                      value: SurveyQuestionBranchingType.NextQuestion,
                  },
              ]
            : []),

        // "Confirmation message" option
        {
            label: 'Confirmation message',
            value: SurveyQuestionBranchingType.End,
        },

        // Individual question options
        ...availableQuestions,
    ]

    const handleResponseBranchingSelection = (responseValue: string | number, nextStep: string): void => {
        const { type: branchingType, specificQuestionIndex } = dropdownValueToBranchingConfig(nextStep)

        setResponseBasedBranchingForQuestion(questionIndex, responseValue, branchingType, specificQuestionIndex)
    }

    return (
        <div className="mt-2 flex flex-col gap-2">
            {responseConfig.map(({ value, label }, i) => (
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
                                handleResponseBranchingSelection(value, nextStep)
                            }}
                            options={responseDestinationOptions}
                        />
                    </div>
                </div>
            ))}
        </div>
    )
}
