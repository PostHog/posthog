import { IconCode, IconCopy } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { allOperatorsMapping } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import React, { useState } from 'react'
import { QUESTION_TYPE_ICON_MAP, SURVEY_RESPONSE_PROPERTY, SurveyQuestionLabel } from 'scenes/surveys/constants'
import { getSurveyResponseKey } from 'scenes/surveys/utils'

import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyQuestionType,
} from '~/types'

import { surveyLogic } from './surveyLogic'
import { SurveySQLHelper } from './SurveySQLHelper'

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

function CopyResponseKeyButton({ questionId }: { questionId: string }): JSX.Element {
    return (
        <button
            onClick={() => void copyToClipboard(`${SURVEY_RESPONSE_PROPERTY}_${questionId}`, 'survey response key')}
            className="flex items-center cursor-pointer gap-1"
        >
            <IconCopy />
            Copy survey response key
        </button>
    )
}

function _SurveyResponseFilters(): JSX.Element {
    const { survey, answerFilters, propertyFilters } = useValues(surveyLogic)
    const { setAnswerFilters, setPropertyFilters } = useActions(surveyLogic)
    const [sqlHelperOpen, setSqlHelperOpen] = useState(false)

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
        setAnswerFilters(newFilters)
    }

    const getFilterForQuestion = (questionIndex: number): EventPropertyFilter | undefined => {
        const filter = answerFilters.find((f) => f.key === getSurveyResponseKey(questionIndex))
        return filter
    }

    // Get the list of questions that have filters applied
    const questionWithFiltersAvailable = (survey as Survey).questions
        .map((question, index) => {
            return {
                ...question,
                questionIndex: index,
            }
        })
        .filter((question) => {
            const operators = OPERATOR_OPTIONS[question.type] || []
            return operators.length > 0
        })

    return (
        <div className="deprecated-space-y-2">
            <div className="flex justify-between items-center">
                <h3 className="m-0">Filter survey results</h3>
                <LemonButton size="small" type="secondary" icon={<IconCode />} onClick={() => setSqlHelperOpen(true)}>
                    Get SQL Query
                </LemonButton>
            </div>
            {questionWithFiltersAvailable.length > 0 && (
                <div className="border rounded">
                    <div className="grid grid-cols-6 gap-2 px-2 py-2 border-b bg-bg-light">
                        <div className="col-span-3 font-semibold">Question</div>
                        <div className="font-semibold">Filter type</div>
                        <div className="col-span-2 font-semibold">Value</div>
                    </div>
                    <div>
                        {questionWithFiltersAvailable.map((question, index) => {
                            const currentFilter = getFilterForQuestion(question.questionIndex)
                            const operators = OPERATOR_OPTIONS[question.type] || []

                            return (
                                <React.Fragment key={question.id ?? question.questionIndex}>
                                    {index > 0 && <LemonDivider className="my-0" label={FilterLogicalOperator.And} />}
                                    <div className="grid grid-cols-6 gap-2 p-2 items-center hover:bg-bg-light transition-all">
                                        <div className="col-span-3">
                                            <span className="font-medium">{question.question}</span>
                                            <div className="text-muted text-xs flex gap-4">
                                                <span className="flex items-center gap-1">
                                                    {QUESTION_TYPE_ICON_MAP[question.type]}
                                                    {SurveyQuestionLabel[question.type]}
                                                </span>
                                                {question.id && <CopyResponseKeyButton questionId={question.id} />}
                                            </div>
                                        </div>
                                        <div>
                                            <LemonSelect
                                                value={currentFilter?.operator}
                                                onChange={(val) =>
                                                    handleUpdateFilter(question.questionIndex, 'operator', val)
                                                }
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
                                                        propertyKey={`${SURVEY_RESPONSE_PROPERTY}_${question.id}`}
                                                        type={PropertyFilterType.Event}
                                                        operator={currentFilter.operator}
                                                        value={currentFilter.value || []}
                                                        onSet={(value: any) =>
                                                            handleUpdateFilter(question.questionIndex, 'value', value)
                                                        }
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
                                </React.Fragment>
                            )
                        })}
                    </div>
                </div>
            )}
            <div className="w-fit">
                <PropertyFilters
                    propertyFilters={propertyFilters}
                    onChange={setPropertyFilters}
                    pageKey="survey-results"
                    buttonText={questionWithFiltersAvailable.length > 1 ? 'More filters' : 'Add filters'}
                />
            </div>

            <SurveySQLHelper isOpen={sqlHelperOpen} onClose={() => setSqlHelperOpen(false)} />
        </div>
    )
}

export const SurveyResponseFilters = React.memo(_SurveyResponseFilters)
