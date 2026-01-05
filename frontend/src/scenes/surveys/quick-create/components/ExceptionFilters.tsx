import { useActions, useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { AnyPropertyFilter, SurveyEventsWithProperties } from '~/types'

import {
    SUPPORTED_OPERATORS,
    convertArrayToPropertyFilters,
    convertPropertyFiltersToArray,
} from '../../SurveyEventTrigger'
import { quickSurveyFormLogic } from '../quickSurveyFormLogic'

const EXCEPTION_PROPERTY_ALLOW_LIST = ['$exception_types', '$exception_values', '$exception_handled']

export function ExceptionFilters(): JSX.Element {
    const { surveyForm } = useValues(quickSurveyFormLogic)
    const { updateConditions } = useActions(quickSurveyFormLogic)

    const exceptionEvent = surveyForm.conditions?.events?.values?.[0]
    const propertyFilters = exceptionEvent?.propertyFilters as SurveyEventsWithProperties['propertyFilters']

    const handleFiltersChange = (filters: AnyPropertyFilter[]): void => {
        updateConditions({
            events: {
                values: [
                    {
                        name: '$exception',
                        propertyFilters: convertArrayToPropertyFilters(filters),
                    },
                ],
            },
        })
    }

    return (
        <div className="mt-2">
            <LemonLabel className="mb-2">Exception filters</LemonLabel>
            <div className="border rounded p-3 bg-bg-light">
                <div className="text-xs font-medium text-muted-alt mb-2">
                    Survey will trigger when an exception matches these filters:
                </div>
                <PropertyFilters
                    propertyFilters={convertPropertyFiltersToArray(propertyFilters)}
                    onChange={handleFiltersChange}
                    pageKey="quick-survey-exception-filters"
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    eventNames={['$exception']}
                    buttonText="Add filter"
                    buttonSize="small"
                    operatorAllowlist={SUPPORTED_OPERATORS}
                    propertyAllowList={{ [TaxonomicFilterGroupType.EventProperties]: EXCEPTION_PROPERTY_ALLOW_LIST }}
                />
            </div>
        </div>
    )
}
