import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { allOperatorsMapping } from 'lib/utils'
import { SurveyQuestionLabel } from 'scenes/surveys/constants'
import { getSurveyResponseKey } from 'scenes/surveys/utils'

import { EventPropertyFilter, PropertyFilterType, PropertyOperator, Survey, SurveyQuestionType } from '~/types'

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
        { label: allOperatorsMapping[PropertyOperator.Regex], value: PropertyOperator.Regex },
        { label: allOperatorsMapping[PropertyOperator.NotRegex], value: PropertyOperator.NotRegex },
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
    ],
    [SurveyQuestionType.Link]: [],
}

export function SurveyAnswerFilters(): JSX.Element {
    const { survey, answerFilters } = useValues(surveyLogic)
    const { setAnswerFilters } = useActions(surveyLogic)

    const handleUpdateFilter = (questionIndex: number, field: 'operator' | 'value', value: any): void => {
        const newFilters = [...answerFilters]
        const filterIndex = newFilters.findIndex((f) => f.key === getSurveyResponseKey(questionIndex))

        if (filterIndex >= 0) {
            // Ensure we're working with an EventPropertyFilter
            const existingFilter = newFilters[filterIndex]
            newFilters[filterIndex] = {
                ...existingFilter,
                [field]: value,
                type: PropertyFilterType.Event, // Ensure type is always set
            }
        } else {
            // Create new filter if one doesn't exist
            newFilters.push({
                key: getSurveyResponseKey(questionIndex),
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
                [field]: value,
            })
        }
        setAnswerFilters(newFilters, true)
    }

    const getFilterForQuestion = (questionIndex: number): EventPropertyFilter | undefined => {
        const filter = answerFilters.find((f) => f.key === getSurveyResponseKey(questionIndex))
        return filter
    }

    return (
        <>
            <div className="border rounded-t">
                <div className="grid grid-cols-6 gap-2 px-2 py-2 border-b bg-bg-light">
                    <div className="col-span-3 font-semibold">Question</div>
                    <div className="font-semibold">Filter type</div>
                    <div className="col-span-2 font-semibold">Value</div>
                </div>
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
                                    <div className="text-muted text-xs">{SurveyQuestionLabel[question.type]}</div>
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
                                    {currentFilter?.operator &&
                                        ![PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(
                                            currentFilter.operator
                                        ) && (
                                            <PropertyValue
                                                propertyKey={
                                                    index === 0 ? '$survey_response' : `$survey_response_${index}`
                                                }
                                                type={PropertyFilterType.Event}
                                                operator={currentFilter.operator}
                                                value={currentFilter.value || []}
                                                onSet={(value: any) => handleUpdateFilter(index, 'value', value)}
                                                placeholder={
                                                    question.type === SurveyQuestionType.Rating
                                                        ? 'Enter a number'
                                                        : 'Enter text to match'
                                                }
                                                eventNames={['survey sent']}
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
