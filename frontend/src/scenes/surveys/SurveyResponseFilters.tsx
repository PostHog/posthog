import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconCode, IconCopy, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { allOperatorsMapping } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { QUESTION_TYPE_ICON_MAP, SurveyQuestionLabel } from 'scenes/surveys/constants'
import { getSurveyEndDateForQuery, getSurveyIdBasedResponseKey, getSurveyStartDateForQuery } from 'scenes/surveys/utils'

import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionType,
} from '~/types'

import { SurveySQLHelper } from './SurveySQLHelper'
import { surveyLogic } from './surveyLogic'

type OperatorOption = { label: string; value: PropertyOperator }

const OPERATOR_OPTIONS: Record<SurveyQuestionType, OperatorOption[]> = {
    [SurveyQuestionType.Open]: [
        { label: allOperatorsMapping[PropertyOperator.IContains], value: PropertyOperator.IContains },
        { label: allOperatorsMapping[PropertyOperator.NotIContains], value: PropertyOperator.NotIContains },
        { label: allOperatorsMapping[PropertyOperator.Regex], value: PropertyOperator.Regex },
        { label: allOperatorsMapping[PropertyOperator.NotRegex], value: PropertyOperator.NotRegex },
        { label: allOperatorsMapping[PropertyOperator.Exact], value: PropertyOperator.Exact },
        { label: allOperatorsMapping[PropertyOperator.IsNot], value: PropertyOperator.IsNot },
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
        { label: allOperatorsMapping[PropertyOperator.IsNot], value: PropertyOperator.IsNot },
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
            onClick={() =>
                void copyToClipboard(`${SurveyEventProperties.SURVEY_RESPONSE}_${questionId}`, 'survey response key')
            }
            className="flex cursor-pointer items-center gap-1"
        >
            <IconCopy />
            Copy survey response key
        </button>
    )
}

export const SurveyResponseFilters = React.memo(function SurveyResponseFilters(): JSX.Element {
    const { survey, answerFilters, propertyFilters, defaultAnswerFilters, dateRange } = useValues(surveyLogic)
    const { setAnswerFilters, setPropertyFilters, setDateRange } = useActions(surveyLogic)
    const [sqlHelperOpen, setSqlHelperOpen] = useState(false)

    const handleResetFilters = (): void => {
        setAnswerFilters(defaultAnswerFilters)
        setPropertyFilters([])
        setDateRange({
            date_from: getSurveyStartDateForQuery(survey as Survey),
            date_to: getSurveyEndDateForQuery(survey as Survey),
        })
    }

    const handleUpdateFilter = (questionId: string, field: 'operator' | 'value', value: any): void => {
        const newFilters = [...answerFilters]
        const filterIndex = newFilters.findIndex((f) => f.key === getSurveyIdBasedResponseKey(questionId))

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
                key: getSurveyIdBasedResponseKey(questionId),
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
                [field]: value,
            })
        }
        setAnswerFilters(newFilters)
    }

    const getFilterForQuestion = (questionId: string): EventPropertyFilter | undefined => {
        const filter = answerFilters.find((f) => f.key === getSurveyIdBasedResponseKey(questionId))
        return filter
    }

    // Get the list of questions that have filters applied
    const questionWithFiltersAvailable = (survey as Survey).questions.filter((question) => {
        const operators = OPERATOR_OPTIONS[question.type] || []
        return operators.length > 0
    })

    return (
        <div className="deprecated-space-y-2">
            <div className="flex items-center justify-between">
                <h3 className="m-0">Filter survey results</h3>
                <LemonButton size="small" type="secondary" icon={<IconCode />} onClick={() => setSqlHelperOpen(true)}>
                    Get SQL Query
                </LemonButton>
            </div>
            {questionWithFiltersAvailable.length > 0 && (
                <div className="rounded border">
                    <div className="bg-bg-light grid grid-cols-6 gap-2 border-b px-2 py-2">
                        <div className="col-span-3 font-semibold">Question</div>
                        <div className="font-semibold">Filter type</div>
                        <div className="col-span-2 font-semibold">Value</div>
                    </div>
                    <div>
                        {questionWithFiltersAvailable.map((question, index) => {
                            if (!question.id) {
                                return null
                            }

                            const currentFilter = getFilterForQuestion(question.id)
                            const operators = OPERATOR_OPTIONS[question.type] || []

                            return (
                                <React.Fragment key={question.id}>
                                    {index > 0 && <LemonDivider className="my-0" label={FilterLogicalOperator.And} />}
                                    <div className="hover:bg-bg-light grid grid-cols-6 items-center gap-2 p-2 transition-all">
                                        <div className="col-span-3">
                                            <span className="font-medium">{question.question}</span>
                                            <div className="text-muted flex gap-4 text-xs">
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
                                                    handleUpdateFilter(question.id ?? '', 'operator', val)
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
                                                        propertyKey={`${SurveyEventProperties.SURVEY_RESPONSE}_${question.id}`}
                                                        type={PropertyFilterType.Event}
                                                        operator={currentFilter.operator}
                                                        value={currentFilter.value || []}
                                                        onSet={(value: any) =>
                                                            handleUpdateFilter(question.id ?? '', 'value', value)
                                                        }
                                                        placeholder={
                                                            question.type === SurveyQuestionType.Rating
                                                                ? 'Enter a number'
                                                                : 'Enter text to match'
                                                        }
                                                        eventNames={[SurveyEventName.SENT]}
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
            <div className="flex justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                    <DateFilter
                        dateFrom={dateRange?.date_from}
                        dateTo={dateRange?.date_to}
                        onChange={(dateFrom, dateTo) => setDateRange({ date_from: dateFrom, date_to: dateTo })}
                    />
                    <PropertyFilters
                        propertyFilters={propertyFilters}
                        onChange={setPropertyFilters}
                        pageKey="survey-results"
                        buttonText={questionWithFiltersAvailable.length > 1 ? 'More filters' : 'Add filters'}
                    />
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={handleResetFilters}
                    className="self-start"
                >
                    Reset all filters
                </LemonButton>
            </div>

            <SurveySQLHelper isOpen={sqlHelperOpen} onClose={() => setSqlHelperOpen(false)} />
        </div>
    )
})
