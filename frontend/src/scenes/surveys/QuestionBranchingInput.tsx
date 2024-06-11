import './EditSurvey.scss'

import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SurveyQuestionBranchingType } from '~/types'

import { surveyLogic } from './surveyLogic'

export function QuestionBranchingInput({ index, question }: { index: number; question: any }): JSX.Element {
    const { survey, getBranchingDropdownValue } = useValues(surveyLogic)
    const { setQuestionBranching } = useActions(surveyLogic)

    const availableNextQuestions = survey.questions
        .map((question, questionIndex) => ({
            ...question,
            questionIndex,
        }))
        .filter((_, questionIndex) => index !== questionIndex)

    const branchingDropdownValue = getBranchingDropdownValue(question, index)

    return (
        <>
            <LemonField name="branching" label="After this question, go to:" className="max-w-80">
                <LemonSelect
                    className="max-w-80 whitespace-nowrap"
                    value={branchingDropdownValue}
                    data-attr={`branching-question-${index}`}
                    onSelect={(value) => setQuestionBranching(index, value)}
                    options={[
                        ...(index < survey.questions.length - 1
                            ? [
                                  {
                                      label: 'Next question',
                                      value: SurveyQuestionBranchingType.NextQuestion,
                                  },
                              ]
                            : []),
                        {
                            label: 'Confirmation message',
                            value: SurveyQuestionBranchingType.ConfirmationMessage,
                        },
                        {
                            label: 'Specific question based on answer',
                            value: SurveyQuestionBranchingType.ResponseBased,
                        },
                        ...availableNextQuestions.map((question) => ({
                            label: `${question.questionIndex + 1}. ${question.question}`,
                            value: `${SurveyQuestionBranchingType.SpecificQuestion}:${question.questionIndex}`,
                        })),
                    ]}
                />
            </LemonField>
            {branchingDropdownValue === SurveyQuestionBranchingType.ResponseBased && (
                <div>
                    <em>TODO: dropdowns for the response based branching</em>
                </div>
            )}
        </>
    )
}
