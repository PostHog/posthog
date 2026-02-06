import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCode, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { OPERATOR_OPTIONS } from 'scenes/surveys/SurveyResponseFilters'
import { SurveySQLHelper } from 'scenes/surveys/SurveySQLHelper'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyEndDateForQuery, getSurveyIdBasedResponseKey, getSurveyStartDateForQuery } from 'scenes/surveys/utils'

import { groupsModel } from '~/models/groupsModel'
import {
    AnyPropertyFilter,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

export function SurveyResultsFiltersBar(): JSX.Element {
    const { survey, propertyFilters, defaultAnswerFilters, dateRange, showArchivedResponses } = useValues(surveyLogic)
    const { setAnswerFilters, setPropertyFilters, setDateRange, setShowArchivedResponses } = useActions(surveyLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const [sqlHelperOpen, setSqlHelperOpen] = useState(false)

    const handleResetFilters = (): void => {
        setAnswerFilters(defaultAnswerFilters)
        setPropertyFilters([])
        setDateRange({
            date_from: getSurveyStartDateForQuery(survey as Survey),
            date_to: getSurveyEndDateForQuery(survey as Survey),
        })
    }

    return (
        <div className="flex flex-wrap gap-2 items-center justify-between">
            <div className="flex flex-wrap gap-2 items-center">
                <DateFilter
                    dateFrom={dateRange?.date_from}
                    dateTo={dateRange?.date_to}
                    onChange={(dateFrom, dateTo) => setDateRange({ date_from: dateFrom, date_to: dateTo })}
                />
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
                <LemonButton size="small" type="secondary" icon={<IconRefresh />} onClick={handleResetFilters}>
                    Reset
                </LemonButton>
                <LemonButton size="small" type="secondary" icon={<IconCode />} onClick={() => setSqlHelperOpen(true)}>
                    SQL
                </LemonButton>
            </div>

            <SurveySQLHelper isOpen={sqlHelperOpen} onClose={() => setSqlHelperOpen(false)} />
        </div>
    )
}

export function SurveyQuestionFilter({ question }: { question: SurveyQuestion }): JSX.Element | null {
    const { answerFilters } = useValues(surveyLogic)
    const { setAnswerFilters } = useActions(surveyLogic)

    if (!question.id || question.type === SurveyQuestionType.Link) {
        return null
    }

    const operators = OPERATOR_OPTIONS[question.type] || []
    if (operators.length === 0) {
        return null
    }

    const getFilterForQuestion = (questionId: string): EventPropertyFilter | undefined => {
        return answerFilters.find((filter: AnyPropertyFilter) => filter.key === getSurveyIdBasedResponseKey(questionId))
    }

    const updateFilter = (questionId: string, field: 'operator' | 'value', value: any): void => {
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

    const currentFilter = getFilterForQuestion(question.id)

    return (
        <div className="flex flex-wrap gap-2 items-center">
            <LemonSelect
                size="xsmall"
                value={currentFilter?.operator}
                onChange={(val) => updateFilter(question.id ?? '', 'operator', val)}
                options={operators}
                className="min-w-[140px]"
            />
            {currentFilter?.operator &&
                ![PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(currentFilter.operator) && (
                    <div className="min-w-[220px]">
                        <PropertyValue
                            propertyKey={`${SurveyEventProperties.SURVEY_RESPONSE}_${question.id}`}
                            type={PropertyFilterType.Event}
                            operator={currentFilter.operator}
                            value={currentFilter.value || []}
                            onSet={(value: any) => updateFilter(question.id ?? '', 'value', value)}
                            placeholder={
                                question.type === SurveyQuestionType.Rating ? 'Enter a number' : 'Enter text to match'
                            }
                            eventNames={[SurveyEventName.SENT]}
                        />
                    </div>
                )}
        </div>
    )
}
