import './CohortField.scss'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import React, { useEffect, useMemo } from 'react'
import { cohortFieldLogic } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'
import { useActions, useValues } from 'kea'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { LemonTaxonomicPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import {
    BehavioralFilterKey,
    CohortPersonPropertiesValuesFieldProps,
    CohortFieldBaseProps,
    CohortNumberFieldProps,
    CohortSelectorFieldProps,
    CohortTaxonomicFieldProps,
    CohortTextFieldProps,
} from 'scenes/cohorts/CohortFilters/types'
import { LemonDivider } from 'lib/components/LemonDivider'
import clsx from 'clsx'
import { resolveCohortFieldValue } from 'scenes/cohorts/cohortUtils'
import { cohortsModel } from '~/models/cohortsModel'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyOperator } from '~/types'

let uniqueMemoizedIndex = 0

const useCohortFieldLogic = (props: CohortFieldBaseProps): { logic: ReturnType<typeof cohortFieldLogic.build> } => {
    const cohortFilterLogicKey = useMemo(
        () => props.cohortFilterLogicKey || `cohort-filter-${uniqueMemoizedIndex++}`,
        [props.cohortFilterLogicKey]
    )
    const logic = cohortFieldLogic({ ...props, cohortFilterLogicKey })
    const { onChange } = useActions(logic)

    useEffect(() => {
        if (props.fieldKey) {
            onChange(props.criteria)
        }
    }, [resolveCohortFieldValue(props.criteria, props.fieldKey)])

    return {
        logic,
    }
}

export function CohortSelectorField({
    fieldKey,
    cohortFilterLogicKey,
    criteria,
    fieldOptionGroupTypes,
    placeholder,
    onChange: _onChange,
}: CohortSelectorFieldProps): JSX.Element {
    const { logic } = useCohortFieldLogic({
        fieldKey,
        cohortFilterLogicKey,
        criteria,
        fieldOptionGroupTypes,
        onChange: _onChange,
    })

    const { fieldOptionGroups, currentOption, value } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <LemonButtonWithPopup
            type="secondary"
            className="CohortField"
            sideIcon={undefined}
            popup={{
                overlay: (
                    <div className="CohortField__dropdown">
                        {fieldOptionGroups.map(({ label, type: groupKey, values }, i) => (
                            <div key={i}>
                                {i !== 0 && <LemonDivider />}
                                <h5>{label}</h5>
                                {Object.entries(values).map(([_value, option]) => (
                                    <LemonButton
                                        key={_value}
                                        onClick={() => {
                                            onChange({ [fieldKey]: _value })
                                        }}
                                        type={_value == value ? 'highlighted' : 'stealth'}
                                        fullWidth
                                        data-attr={`cohort-${groupKey}-${_value}-type`}
                                    >
                                        {option.label}
                                    </LemonButton>
                                ))}
                            </div>
                        ))}
                    </div>
                ),
            }}
        >
            {currentOption?.label || <span className="text-muted">{placeholder}</span>}
        </LemonButtonWithPopup>
    )
}

export function CohortTaxonomicField({
    fieldKey,
    cohortFilterLogicKey,
    criteria,
    taxonomicGroupType = TaxonomicFilterGroupType.Events,
    taxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    placeholder = 'Choose event',
    onChange: _onChange,
}: CohortTaxonomicFieldProps): JSX.Element {
    const { logic } = useCohortFieldLogic({
        fieldKey,
        criteria,
        cohortFilterLogicKey,
        onChange: _onChange,
    })

    const { value } = useValues(logic)
    const { onChange } = useActions(logic)
    const { cohortsById } = useValues(cohortsModel)
    const cohortOrOtherValue =
        criteria.type === BehavioralFilterKey.Cohort && fieldKey === 'value_property' && typeof value === 'number'
            ? cohortsById[value]?.name ?? `Cohort ${value}`
            : value

    return (
        <LemonTaxonomicPopup
            className="CohortField"
            type="secondary"
            groupType={taxonomicGroupType}
            value={cohortOrOtherValue as TaxonomicFilterValue}
            onChange={(v, g) => {
                onChange({ [fieldKey]: v, event_type: g })
            }}
            groupTypes={taxonomicGroupTypes}
            placeholder={placeholder}
        />
    )
}

export function CohortPersonPropertiesValuesField({
    fieldKey,
    criteria,
    cohortFilterLogicKey,
    onChange: _onChange,
    propertyKey,
    operator,
}: CohortPersonPropertiesValuesFieldProps): JSX.Element {
    const { logic } = useCohortFieldLogic({
        fieldKey,
        criteria,
        cohortFilterLogicKey,
        onChange: _onChange,
    })
    const { onChange } = useActions(logic)

    return (
        <PropertyValue
            operator={operator || PropertyOperator.Exact}
            propertyKey={propertyKey as string}
            type="person"
            onSet={(newValue: PropertyOperator) => {
                onChange({ [fieldKey]: newValue })
            }}
            placeholder="Enter value..."
            className="CohortField__CohortPersonPropertiesValuesField"
        />
    )
}

export function CohortTextField({ value }: CohortTextFieldProps): JSX.Element {
    return <span className={clsx('CohortField', 'CohortField__CohortTextField')}>{value}</span>
}

export function CohortNumberField({
    fieldKey,
    cohortFilterLogicKey,
    criteria,
    onChange: _onChange,
}: CohortNumberFieldProps): JSX.Element {
    const { logic } = useCohortFieldLogic({
        fieldKey: fieldKey,
        cohortFilterLogicKey,
        criteria,
        onChange: _onChange,
    })
    const { value } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <LemonInput
            type="number"
            value={(value as string | number) ?? undefined}
            onChange={(nextNumber) => {
                onChange({ [fieldKey]: nextNumber })
            }}
            className={clsx('CohortField', 'CohortField__CohortNumberField')}
        />
    )
}
