import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconCopy, IconFilter, IconGraph, IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOptions, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { QUESTION_TYPE_ICON_MAP, SurveyQuestionLabel } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { OPERATOR_OPTIONS } from 'scenes/surveys/SurveyResponseFilters'
import { getSurveyEndDateForQuery, getSurveyIdBasedResponseKey, getSurveyStartDateForQuery } from 'scenes/surveys/utils'

import { groupsModel } from '~/models/groupsModel'
import {
    AnyPropertyFilter,
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionType,
} from '~/types'

function CopyResponseKeyButton({ questionId }: { questionId: string }): JSX.Element {
    return (
        <button
            onClick={() =>
                void copyToClipboard(`${SurveyEventProperties.SURVEY_RESPONSE}_${questionId}`, 'survey response key')
            }
            className="flex items-center cursor-pointer gap-1"
        >
            <IconCopy />
            Copy survey response key
        </button>
    )
}

export function SurveyResultsFiltersBar(): JSX.Element {
    const {
        survey,
        answerFilters,
        propertyFilters,
        defaultAnswerFilters,
        dateRange,
        showArchivedResponses,
        surveyAsInsightURL,
    } = useValues(surveyLogic)
    const { setAnswerFilters, setPropertyFilters, setDateRange, setShowArchivedResponses } = useActions(surveyLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const [questionFiltersExpanded, setQuestionFiltersExpanded] = useState(false)

    const handleResetFilters = (): void => {
        setAnswerFilters(defaultAnswerFilters)
        setPropertyFilters([])
        setDateRange({
            date_from: getSurveyStartDateForQuery(survey as Survey),
            date_to: getSurveyEndDateForQuery(survey as Survey),
        })
    }

    const handleUpdateFilter = (
        questionId: string,
        field: 'operator' | 'value',
        value: PropertyOperator | string | string[]
    ): void => {
        const newFilters = [...answerFilters]
        const filterIndex = newFilters.findIndex((f) => f.key === getSurveyIdBasedResponseKey(questionId))

        if (filterIndex >= 0) {
            const existingFilter = newFilters[filterIndex]
            newFilters[filterIndex] = {
                ...existingFilter,
                [field]: value,
                type: PropertyFilterType.Event,
            }
        } else {
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
        return answerFilters.find((f: AnyPropertyFilter) => f.key === getSurveyIdBasedResponseKey(questionId))
    }

    const questionWithFiltersAvailable = (survey as Survey).questions.filter((question) => {
        const operators = OPERATOR_OPTIONS[question.type] || []
        return operators.length > 0
    })

    const activeAnswerFiltersCount = questionWithFiltersAvailable.filter((question) => {
        if (!question.id) {
            return false
        }
        const filter = getFilterForQuestion(question.id)
        if (!filter?.value) {
            return false
        }
        return Array.isArray(filter.value) ? filter.value.length > 0 : filter.value !== ''
    }).length

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <div className="flex flex-wrap gap-2 items-center">
                    <DateFilter
                        dateFrom={dateRange?.date_from}
                        dateTo={dateRange?.date_to}
                        onChange={(dateFrom, dateTo) => setDateRange({ date_from: dateFrom, date_to: dateTo })}
                    />
                    {questionWithFiltersAvailable.length > 0 && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconFilter />}
                            sideIcon={questionFiltersExpanded ? <IconX /> : null}
                            onClick={() => setQuestionFiltersExpanded(!questionFiltersExpanded)}
                            active={questionFiltersExpanded || activeAnswerFiltersCount > 0}
                        >
                            Filter by response
                            {activeAnswerFiltersCount > 0 && ` (${activeAnswerFiltersCount})`}
                        </LemonButton>
                    )}
                    <PropertyFilters
                        propertyFilters={propertyFilters}
                        onChange={setPropertyFilters}
                        pageKey="survey-results"
                        buttonText="Add filter"
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.HogQLExpression,
                            ...groupsTaxonomicTypes,
                        ]}
                    />
                </div>
                <div className="flex flex-wrap gap-2 items-center">
                    <LemonSwitch
                        checked={showArchivedResponses}
                        onChange={setShowArchivedResponses}
                        label="Show archived"
                    />
                    <LemonButton size="small" type="secondary" icon={<IconGraph />} to={surveyAsInsightURL}>
                        View insights
                    </LemonButton>
                    <LemonButton size="small" type="secondary" icon={<IconRefresh />} onClick={handleResetFilters}>
                        Reset filters
                    </LemonButton>
                </div>
            </div>

            {questionFiltersExpanded && questionWithFiltersAvailable.length > 0 && (
                <div className="border rounded bg-bg-light overflow-hidden">
                    {questionWithFiltersAvailable.map((question, index) => {
                        if (!question.id) {
                            return null
                        }

                        const currentFilter = getFilterForQuestion(question.id)
                        const operators = OPERATOR_OPTIONS[question.type] || []

                        return (
                            <React.Fragment key={question.id}>
                                {index > 0 && <LemonDivider className="my-0" label={FilterLogicalOperator.And} />}
                                <div className="grid grid-cols-6 gap-2 p-2 items-center">
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
                                            onChange={(val) => handleUpdateFilter(question.id ?? '', 'operator', val)}
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
                                                    onSet={(value: string | string[]) =>
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
            )}
        </div>
    )
}
