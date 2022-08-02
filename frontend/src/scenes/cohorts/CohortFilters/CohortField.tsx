import './CohortField.scss'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import React, { useMemo } from 'react'
import { cohortFieldLogic } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'
import { useActions, useValues } from 'kea'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { LemonTaxonomicPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import {
    CohortPersonPropertiesValuesFieldProps,
    CohortFieldBaseProps,
    CohortNumberFieldProps,
    CohortSelectorFieldProps,
    CohortTaxonomicFieldProps,
    CohortTextFieldProps,
} from 'scenes/cohorts/CohortFilters/types'
import { LemonDivider } from 'lib/components/LemonDivider'
import clsx from 'clsx'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyFilterValue, PropertyOperator } from '~/types'

let uniqueMemoizedIndex = 0

const useCohortFieldLogic = (props: CohortFieldBaseProps): { logic: ReturnType<typeof cohortFieldLogic.build> } => {
    const cohortFilterLogicKey = useMemo(
        () => props.cohortFilterLogicKey || `cohort-filter-${uniqueMemoizedIndex++}`,
        [props.cohortFilterLogicKey]
    )
    return {
        logic: cohortFieldLogic({ ...props, cohortFilterLogicKey }),
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
            data-attr={`cohort-selector-field-${fieldKey}`}
            popup={{
                className: 'Popup__CohortField',
                placement: 'bottom-start',
                overlay: (
                    <div className="CohortField__dropdown">
                        {fieldOptionGroups.map(({ label, type: groupKey, values }, i) =>
                            Object.keys(values).length != 0 ? (
                                <div key={i}>
                                    {i !== 0 && <LemonDivider />}
                                    <h5>{label}</h5>
                                    {Object.entries(values).map(([_value, option]) => (
                                        <LemonButton
                                            key={_value}
                                            onClick={() => {
                                                onChange({ [fieldKey]: _value })
                                            }}
                                            type={'stealth'}
                                            active={_value == value}
                                            fullWidth
                                            data-attr={`cohort-${groupKey}-${_value}-type`}
                                        >
                                            {option.label}
                                        </LemonButton>
                                    ))}
                                </div>
                            ) : null
                        )}
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
    groupTypeFieldKey = 'event_type',
    cohortFilterLogicKey,
    criteria,
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

    const { calculatedValue, calculatedValueLoading } = useValues(logic)
    const { onChange } = useActions(logic)
    const groupType = criteria[groupTypeFieldKey] as TaxonomicFilterGroupType

    return (
        <LemonTaxonomicPopup
            className="CohortField"
            type="secondary"
            groupType={groupType}
            loading={calculatedValueLoading(groupType)}
            value={calculatedValue(groupType) as TaxonomicFilterValue}
            onChange={(v, g) => {
                onChange({ [fieldKey]: v, [groupTypeFieldKey]: g })
            }}
            groupTypes={taxonomicGroupTypes}
            placeholder={placeholder}
            data-attr={`cohort-taxonomic-field-${fieldKey}`}
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
    const { value } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <PropertyValue
            className={clsx('CohortField', 'CohortField__CohortPersonPropertiesValuesField')}
            operator={operator || PropertyOperator.Exact}
            propertyKey={propertyKey as string}
            type="person"
            value={value as PropertyFilterValue}
            onSet={(newValue: PropertyOperator) => {
                onChange({ [fieldKey]: newValue })
            }}
            placeholder="Enter value..."
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
        fieldKey,
        cohortFilterLogicKey,
        criteria,
        onChange: _onChange,
    })
    const { value } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <LemonInput
            type="number"
            value={(value as number) ?? undefined}
            onChange={(nextNumber) => {
                onChange({ [fieldKey]: nextNumber })
            }}
            min={1}
            step={1}
            className={clsx('CohortField', 'CohortField__CohortNumberField')}
        />
    )
}
