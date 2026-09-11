import { useActions, useValues } from 'kea'
import React from 'react'

import { IconCopy, IconEllipsis, IconFilter, IconGraph, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonMenu, LemonSelect, LemonSelectOptions, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { QUESTION_TYPE_ICON_MAP, SurveyQuestionLabel } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { OPERATOR_OPTIONS } from 'scenes/surveys/SurveyResponseFilters'
import { getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

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
        hasActiveFilters,
        activeResultsFilterCount,
        resultsFiltersExpanded,
        dateRange,
        showArchivedResponses,
        surveyAsInsightURL,
    } = useValues(surveyLogic)
    const {
        setAnswerFilters,
        setPropertyFilters,
        setDateRange,
        setShowArchivedResponses,
        clearFilters,
        setResultsFiltersExpanded,
    } = useActions(surveyLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
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

    return (
        <div className="@container/survey-filters flex flex-col gap-4">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <div className="flex flex-wrap gap-2 items-center">
                    <DateFilter
                        dateFrom={dateRange?.date_from}
                        dateTo={dateRange?.date_to}
                        onChange={(dateFrom, dateTo) => setDateRange({ date_from: dateFrom, date_to: dateTo })}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFilter />}
                        sideIcon={
                            activeResultsFilterCount > 0 ? (
                                <LemonBadge.Number count={activeResultsFilterCount} size="small" />
                            ) : undefined
                        }
                        onClick={() => setResultsFiltersExpanded(!resultsFiltersExpanded)}
                        active={resultsFiltersExpanded || activeResultsFilterCount > 0}
                        aria-expanded={resultsFiltersExpanded}
                        aria-controls={resultsFiltersExpanded ? 'survey-results-filters' : undefined}
                        data-attr="survey-results-filters-toggle"
                    >
                        Filters
                    </LemonButton>
                    {(hasActiveFilters || showArchivedResponses) && (
                        <LemonButton
                            size="small"
                            type="tertiary"
                            onClick={clearFilters}
                            data-attr="survey-results-clear-filters"
                        >
                            Clear filters
                        </LemonButton>
                    )}
                </div>
                <LemonMenu items={[{ label: 'View insights', icon: <IconGraph />, to: surveyAsInsightURL }]}>
                    <LemonButton
                        size="small"
                        icon={<IconEllipsis />}
                        aria-label="More result actions"
                        tooltip="More result actions"
                        data-attr="survey-results-more-actions"
                    />
                </LemonMenu>
            </div>

            {resultsFiltersExpanded && (
                <section
                    id="survey-results-filters"
                    aria-label="Survey filters"
                    className="border rounded bg-bg-light p-4 flex flex-col gap-4"
                >
                    <div className="flex items-center justify-between gap-2">
                        <h4 className="m-0">Filters</h4>
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            aria-label="Close filters"
                            onClick={() => setResultsFiltersExpanded(false)}
                            data-attr="survey-results-filters-close"
                        />
                    </div>
                    <div className="flex flex-col gap-2">
                        <h5 className="m-0">Properties</h5>
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
                    <LemonSwitch
                        checked={showArchivedResponses}
                        onChange={setShowArchivedResponses}
                        label="Show archived"
                    />
                    {questionWithFiltersAvailable.length > 0 && <h5 className="m-0">Responses</h5>}
                    <div className="flex flex-col gap-3">
                        {questionWithFiltersAvailable.map((question, index) => {
                            if (!question.id) {
                                return null
                            }

                            const currentFilter = getFilterForQuestion(question.id)
                            const operators = OPERATOR_OPTIONS[question.type] || []

                            return (
                                <React.Fragment key={question.id}>
                                    {index > 0 && <LemonDivider className="my-0" label={FilterLogicalOperator.And} />}
                                    <div className="grid grid-cols-1 @min-[48rem]/survey-filters:grid-cols-6 gap-3 items-center">
                                        <div className="@min-[48rem]/survey-filters:col-span-3">
                                            <span className="font-medium">{question.question}</span>
                                            <div className="text-muted text-xs flex flex-wrap gap-x-4 gap-y-1">
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
                                        <div className="@min-[48rem]/survey-filters:col-span-2">
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
                </section>
            )}
        </div>
    )
}
