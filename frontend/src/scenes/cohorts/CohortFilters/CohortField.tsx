import './CohortField.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { formatDate } from 'lib/utils'
import { cohortFieldLogic } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'
import {
    CohortEventFiltersFieldProps,
    CohortFieldBaseProps,
    CohortNumberFieldProps,
    CohortPersonPropertiesValuesFieldProps,
    CohortRelativeAndExactTimeFieldProps,
    CohortSelectorFieldProps,
    CohortTaxonomicFieldProps,
    CohortTextFieldProps,
} from 'scenes/cohorts/CohortFilters/types'

import { AnyPropertyFilter, PropertyFilterType, PropertyFilterValue, PropertyOperator } from '~/types'

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
        <LemonButtonWithDropdown
            type="secondary"
            sideIcon={undefined}
            data-attr={`cohort-selector-field-${fieldKey}`}
            dropdown={{
                className: 'Popover__CohortField',
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
            <span className="font-medium">
                {currentOption?.label || <span className="text-secondary">{placeholder}</span>}
            </span>
        </LemonButtonWithDropdown>
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
        <TaxonomicPopover
            className="CohortField"
            groupType={groupType}
            loading={calculatedValueLoading(groupType)}
            value={calculatedValue(groupType) as TaxonomicFilterValue}
            onChange={(v, g) => {
                onChange({ [fieldKey]: v, [groupTypeFieldKey]: g })
            }}
            excludedProperties={{
                [TaxonomicFilterGroupType.Events]: [null], // "All events" isn't supported by Cohorts currently
            }}
            groupTypes={taxonomicGroupTypes}
            placeholder={placeholder}
            data-attr={`cohort-taxonomic-field-${fieldKey}`}
            renderValue={(value) =>
                value ? (
                    <PropertyKeyInfo value={value as string} type={groupType} />
                ) : (
                    <span className="text-secondary">{placeholder}</span>
                )
            }
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
            operator={operator || PropertyOperator.Exact}
            propertyKey={propertyKey as string}
            type={PropertyFilterType.Person}
            value={value as PropertyFilterValue}
            onSet={(newValue: PropertyOperator) => {
                onChange({ [fieldKey]: newValue })
            }}
            placeholder="Enter value..."
        />
    )
}

export function CohortEventFiltersField({
    fieldKey,
    criteria,
    cohortFilterLogicKey,
    onChange: _onChange,
    groupIndex,
    index,
}: CohortEventFiltersFieldProps): JSX.Element {
    const { logic } = useCohortFieldLogic({
        fieldKey,
        criteria,
        cohortFilterLogicKey,
        onChange: _onChange,
    })
    const { value } = useValues(logic)
    const { onChange } = useActions(logic)
    const componentRef = useRef<HTMLDivElement>(null)

    const valueExists = ((value as AnyPropertyFilter[]) || []).length > 0

    useEffect(() => {
        // :TRICKY: We check parent has CohortCriteriaRow__Criteria__Field class and add basis-full class if value exists
        // We need to do this because of how this list is generated, and we need to add a line-break programatically
        // when the PropertyFilters take up too much space.
        // Since the list of children is declared in the parent component, we can't add a class to the parent directly, without
        // adding a lot of annoying complexity to the parent component.
        // This is a hacky solution, but it works 🙈.

        // find parent with className CohortCriteriaRow__Criteria__Field and add basis-full class if value exists
        const parent = componentRef.current?.closest('.CohortCriteriaRow__Criteria__Field')
        if (parent) {
            if (valueExists) {
                parent.classList.add('basis-full')
            } else {
                parent.classList.remove('basis-full')
            }
        }
    }, [componentRef, value]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div ref={componentRef}>
            <PropertyFilters
                propertyFilters={(value as AnyPropertyFilter[]) || []}
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
                onChange={(newValue: AnyPropertyFilter[]) => {
                    onChange({ [fieldKey]: newValue })
                }}
                pageKey={`${fieldKey}-${groupIndex}-${index}`}
                eventNames={criteria?.key ? [criteria?.key] : []}
                disablePopover
                hasRowOperator={valueExists ? true : false}
                sendAllKeyUpdates
            />
        </div>
    )
}

export function CohortRelativeAndExactTimeField({
    fieldKey,
    criteria,
    cohortFilterLogicKey,
    onChange: _onChange,
}: CohortRelativeAndExactTimeFieldProps): JSX.Element {
    const { logic } = useCohortFieldLogic({
        fieldKey,
        criteria,
        cohortFilterLogicKey,
        onChange: _onChange,
    })
    // This replaces the old TimeUnit and TimeInterval filters
    // and combines them with a relative+exact time option.
    // This is more inline with rest of analytics filters and make things much nicer here.
    const { value } = useValues(logic)
    const { onChange } = useActions(logic)

    return (
        <DateFilter
            dateFrom={String(value)}
            onChange={(fromDate) => {
                onChange({ [fieldKey]: fromDate })
            }}
            max={1000}
            isFixedDateMode
            allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
            showCustom
            dateOptions={[
                {
                    key: 'Last 7 days',
                    values: ['-7d'],
                    getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(7, 'd')),
                    defaultInterval: 'day',
                },
                {
                    key: 'Last 30 days',
                    values: ['-30d'],
                    getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(14, 'd')),
                    defaultInterval: 'day',
                },
            ]}
            size="medium"
            makeLabel={(_, startOfRange) => (
                <span className="hide-when-small">Matches all values after {startOfRange} if evaluated today.</span>
            )}
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
