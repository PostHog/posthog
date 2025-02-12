import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { allOperatorsMapping } from 'lib/utils'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, Survey, SurveyQuestionType } from '~/types'

import { surveyLogic } from './surveyLogic'

type OperatorOption = { label: string; value: PropertyOperator }

const OPERATOR_OPTIONS: Record<SurveyQuestionType, OperatorOption[]> = {
    [SurveyQuestionType.Open]: [
        { label: allOperatorsMapping[PropertyOperator.IContains], value: PropertyOperator.IContains },
        { label: allOperatorsMapping[PropertyOperator.NotIContains], value: PropertyOperator.NotIContains },
        { label: allOperatorsMapping[PropertyOperator.Regex], value: PropertyOperator.Regex },
        { label: allOperatorsMapping[PropertyOperator.NotRegex], value: PropertyOperator.NotRegex },
        { label: allOperatorsMapping[PropertyOperator.Exact], value: PropertyOperator.Exact },
    ],
    [SurveyQuestionType.Rating]: [
        { label: allOperatorsMapping[PropertyOperator.Exact], value: PropertyOperator.Exact },
        { label: allOperatorsMapping[PropertyOperator.IsNot], value: PropertyOperator.IsNot },
        { label: allOperatorsMapping[PropertyOperator.GreaterThan], value: PropertyOperator.GreaterThan },
        { label: allOperatorsMapping[PropertyOperator.LessThan], value: PropertyOperator.LessThan },
    ],
    [SurveyQuestionType.SingleChoice]: [
        { label: allOperatorsMapping[PropertyOperator.IContains], value: PropertyOperator.IContains },
        { label: allOperatorsMapping[PropertyOperator.NotIContains], value: PropertyOperator.NotIContains },
        { label: allOperatorsMapping[PropertyOperator.Regex], value: PropertyOperator.Regex },
        { label: allOperatorsMapping[PropertyOperator.NotRegex], value: PropertyOperator.NotRegex },
        { label: allOperatorsMapping[PropertyOperator.Exact], value: PropertyOperator.Exact },
    ],
    [SurveyQuestionType.MultipleChoice]: [
        { label: allOperatorsMapping[PropertyOperator.IContains], value: PropertyOperator.IContains },
        { label: allOperatorsMapping[PropertyOperator.NotIContains], value: PropertyOperator.NotIContains },
        { label: allOperatorsMapping[PropertyOperator.Regex], value: PropertyOperator.Regex },
        { label: allOperatorsMapping[PropertyOperator.NotRegex], value: PropertyOperator.NotRegex },
        { label: allOperatorsMapping[PropertyOperator.Exact], value: PropertyOperator.Exact },
    ],
    [SurveyQuestionType.Link]: [],
}

const QUESTION_TYPE_LABEL: Record<SurveyQuestionType, string> = {
    [SurveyQuestionType.Open]: 'Text response',
    [SurveyQuestionType.Rating]: 'Numeric rating',
    [SurveyQuestionType.SingleChoice]: 'Single choice',
    [SurveyQuestionType.MultipleChoice]: 'Multiple choice',
    [SurveyQuestionType.Link]: 'Link',
}

export function SurveyAnswerFilters(): JSX.Element {
    const { survey, answerFilters } = useValues(surveyLogic)
    const { setAnswerFilters } = useActions(surveyLogic)

    const handleUpdateFilter = (questionIndex: number, field: 'operator' | 'value', value: any): void => {
        const newFilters = [...answerFilters]
        const filterIndex = newFilters.findIndex(
            (f) => f.key === (questionIndex === 0 ? '$survey_response' : `$survey_response_${questionIndex}`)
        )

        if (filterIndex >= 0) {
            newFilters[filterIndex] = {
                ...newFilters[filterIndex],
                [field]: value,
            }
            setAnswerFilters(newFilters)
        }
    }

    const getFilterForQuestion = (questionIndex: number): AnyPropertyFilter | undefined => {
        if (questionIndex === 0) {
            return answerFilters.find((f) => f.key === '$survey_response')
        }
        return answerFilters.find((f) => f.key === `$survey_response_${questionIndex}`)
    }

    return (
        <>
            {/* Header */}
            <div className="border rounded-t">
                <div className="grid grid-cols-6 gap-2 px-2 py-2 border-b bg-bg-light">
                    <div className="col-span-3 font-semibold">Question</div>
                    <div className="font-semibold">Filter type</div>
                    <div className="col-span-2 font-semibold">Value</div>
                </div>
                {/* Rows */}
                <div>
                    {(survey as Survey).questions.map((question, index) => {
                        const currentFilter = getFilterForQuestion(index)
                        const operators = OPERATOR_OPTIONS[question.type] || []

                        if (operators.length === 0) {
                            return null // Skip questions that don't support filtering (like Link type)
                        }

                        return (
                            <div
                                key={index}
                                className="grid grid-cols-6 gap-2 px-2 py-2 items-center border-b last:border-b-0 hover:bg-bg-light transition-all"
                            >
                                <div className="col-span-3">
                                    <span className="font-medium">{question.question}</span>
                                    <div className="text-muted text-xs">{QUESTION_TYPE_LABEL[question.type]}</div>
                                </div>
                                <div>
                                    <LemonSelect
                                        value={currentFilter?.operator}
                                        onChange={(val) => handleUpdateFilter(index, 'operator', val)}
                                        options={operators as LemonSelectOptions<PropertyOperator>}
                                        className="w-full"
                                    />
                                </div>
                                <div className="col-span-2">
                                    {![PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(
                                        currentFilter?.operator as PropertyOperator
                                    ) && (
                                        <PropertyValue
                                            propertyKey={index === 0 ? '$survey_response' : `$survey_response_${index}`}
                                            type={PropertyFilterType.Event}
                                            operator={currentFilter?.operator as PropertyOperator}
                                            value={currentFilter?.value || []}
                                            onSet={(value: string[]) => handleUpdateFilter(index, 'value', value)}
                                            placeholder={
                                                question.type === SurveyQuestionType.Rating
                                                    ? 'Enter a number'
                                                    : question.type === SurveyQuestionType.Open
                                                    ? 'Enter text to match'
                                                    : 'Select values'
                                            }
                                        />
                                    )}
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>
        </>
    )
}
