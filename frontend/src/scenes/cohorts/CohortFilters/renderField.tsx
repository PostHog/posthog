import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    CohortEventFiltersField,
    CohortMathOperatorField,
    CohortNumberField,
    CohortPersonPropertiesValuesField,
    CohortRelativeAndExactTimeField,
    CohortSelectorField,
    CohortTaxonomicField,
    CohortTextField,
} from 'scenes/cohorts/CohortFilters/CohortField'
import {
    CohortEventFiltersFieldProps,
    CohortFieldProps,
    CohortNumberFieldProps,
    CohortPersonPropertiesValuesFieldProps,
    CohortRelativeAndExactTimeFieldProps,
    CohortTaxonomicFieldProps,
    CohortTextFieldProps,
    FieldOptionsType,
    FilterType,
} from 'scenes/cohorts/CohortFilters/types'

import { PropertyOperator } from '~/types'

// Building blocks of a row
export const renderField: Record<FilterType, (props: CohortFieldProps) => JSX.Element> = {
    [FilterType.Behavioral]: function _renderField(p) {
        return (
            <CohortSelectorField
                {...p}
                fieldOptionGroupTypes={[
                    FieldOptionsType.EventBehavioral,
                    FieldOptionsType.PersonPropertyBehavioral,
                    FieldOptionsType.CohortBehavioral,
                    FieldOptionsType.LifecycleBehavioral,
                ]}
            />
        )
    },
    [FilterType.Aggregation]: function _renderField(p) {
        return (
            <CohortSelectorField
                {...p}
                fieldOptionGroupTypes={[FieldOptionsType.EventAggregation, FieldOptionsType.PropertyAggregation]}
            />
        )
    },
    [FilterType.Actors]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.Actors]} />
    },
    [FilterType.TimeUnit]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.TimeUnits]} />
    },
    [FilterType.DateOperator]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.DateOperators]} />
    },
    [FilterType.MathOperator]: function _renderField(p) {
        return <CohortMathOperatorField {...p} />
    },
    [FilterType.EventsAndActionsMathOperator]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.EventsAndActionsMathOperators]} />
    },
    [FilterType.Value]: function _renderField(p) {
        return <CohortSelectorField {...p} fieldOptionGroupTypes={[FieldOptionsType.ValueOptions]} />
    },
    [FilterType.Text]: function _renderField(p) {
        const _p = p as CohortTextFieldProps
        return <CohortTextField {..._p} value={String(_p?.value ?? '')} />
    },
    [FilterType.EventsAndActions]: function _renderField(p) {
        return (
            <CohortTaxonomicField
                {...(p as CohortTaxonomicFieldProps)}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                placeholder="Choose event or action"
            />
        )
    },
    [FilterType.PersonProperties]: function _renderField(p) {
        return (
            <CohortTaxonomicField
                {...(p as CohortTaxonomicFieldProps)}
                hideUnsupportedRecentOperators
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.PersonMetadata,
                ]}
                placeholder="Choose person property"
            />
        )
    },
    [FilterType.EventFilters]: function _renderField(p) {
        return <CohortEventFiltersField {...(p as CohortEventFiltersFieldProps)} />
    },
    [FilterType.PersonPropertyValues]: function _renderField(p) {
        return p.criteria['operator'] &&
            [PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(p.criteria['operator']) ? (
            <></>
        ) : (
            <CohortPersonPropertiesValuesField
                {...(p as CohortPersonPropertiesValuesFieldProps)}
                propertyKey={p.criteria.key}
                operator={p.criteria['operator'] ?? undefined}
            />
        )
    },
    [FilterType.Number]: function _renderField(p) {
        return <CohortNumberField {...(p as CohortNumberFieldProps)} />
    },
    [FilterType.NumberTicker]: function _renderField(p) {
        return <CohortNumberField {...(p as CohortNumberFieldProps)} />
    },
    [FilterType.CohortValues]: function _renderField(p) {
        return (
            <CohortTaxonomicField
                {...(p as CohortTaxonomicFieldProps)}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]}
                placeholder="Choose cohort"
            />
        )
    },
    [FilterType.RelativeAndExactTime]: function _renderField(p) {
        return <CohortRelativeAndExactTimeField {...(p as CohortRelativeAndExactTimeFieldProps)} />
    },
    [FilterType.EventType]: function _renderField() {
        return <></>
    },
    [FilterType.CohortId]: function _renderField() {
        return <></>
    },
}
