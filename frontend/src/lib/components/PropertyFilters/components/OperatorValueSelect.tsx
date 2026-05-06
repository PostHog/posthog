import { useValues } from 'kea'
import { RE2JS } from 're2js'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonDropdownProps, LemonSelect, LemonSelectProps, LemonSelectSection } from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    allOperatorsMapping,
    chooseOperatorMap,
    isMobile,
    isOperatorCohort,
    isOperatorDate,
    isOperatorFlag,
    isOperatorMulti,
    isOperatorRange,
    isOperatorRegex,
    isOperatorSemver,
} from 'lib/utils'
import { RE2_DOCS_LINK, formatRE2Error } from 'lib/utils/regexp'

import {
    GroupTypeIndex,
    PropertyDefinition,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    PropertyType,
} from '~/types'

import { PropertyValue } from './PropertyValue'

// OTel span.kind enum (https://opentelemetry.io/docs/specs/otel/trace/api/#spankind).
const SPAN_KIND_OPTIONS: { key: number; label: string }[] = [
    { key: 0, label: 'Unspecified' },
    { key: 1, label: 'Internal' },
    { key: 2, label: 'Server' },
    { key: 3, label: 'Client' },
    { key: 4, label: 'Producer' },
    { key: 5, label: 'Consumer' },
]

// OTel status_code. 'Unset' (0) is conflated with 'OK' (1) in the filter UI per product decision.
const STATUS_CODE_OPTIONS: { key: number; label: string }[] = [
    { key: 1, label: 'OK' },
    { key: 2, label: 'Error' },
]

function SpanEnumValueSelect({
    options,
    value,
    onChange,
    isMultiSelect,
    size,
}: {
    options: { key: number; label: string }[]
    value?: PropertyFilterValue
    onChange: (value: PropertyFilterValue) => void
    isMultiSelect: boolean
    size?: 'xsmall' | 'small' | 'medium'
}): JSX.Element {
    // Filter value stores labels (e.g. "Server", "OK") so the applied-filter chip renders
    // human text. The backend maps labels back to ints before building the HogQL query.
    const labels = new Set(options.map((o) => o.label))
    const selectedRaw = value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]
    const selectedLabels = selectedRaw.map((v) => String(v)).filter((v) => labels.has(v))

    return (
        <LemonInputSelect
            data-attr="prop-val"
            mode={isMultiSelect ? 'multiple' : 'single'}
            singleValueAsSnack
            allowCustomValues={false}
            value={selectedLabels}
            onChange={(next) => {
                const valid = next.map((v) => String(v)).filter((v) => labels.has(v))
                if (isMultiSelect) {
                    onChange(valid)
                } else {
                    onChange(valid.length > 0 ? valid[0] : null)
                }
            }}
            options={options.map((o) => ({
                key: o.label,
                label: o.label,
            }))}
            size={size}
        />
    )
}

export interface OperatorValueSelectProps {
    type?: PropertyFilterType
    propertyKey?: string
    operator?: PropertyOperator | null
    value?: PropertyFilterValue
    editable: boolean
    placeholder?: string
    endpoint?: string
    onChange: (operator: PropertyOperator, value: PropertyFilterValue) => void
    operatorSelectProps?: Partial<Omit<LemonSelectProps<any>, 'onChange'>>
    eventNames?: string[]
    propertyDefinitions: PropertyDefinition[]
    addRelativeDateTimeOptions?: boolean
    groupTypeIndex?: GroupTypeIndex
    groupKeyNames?: Record<string, string>
    size?: 'xsmall' | 'small' | 'medium'
    startVisible?: LemonDropdownProps['startVisible']
    /**
     * Narrows the *operator dropdown options* shown for the active filter.
     * Flat list — applies to whichever filter type is currently active in this
     * `OperatorValueSelect`. Won't add operators that wouldn't otherwise be valid.
     *
     * Different concern from `excludedOperators` on the picker / `PropertyFilters`:
     * - `operatorAllowlist` (here) governs which entries appear inside the operator
     *   dropdown next to a filter value.
     * - `excludedOperators` governs which *recent property filters* surface in the
     *   picker's Recent tab (and whether the operator dropdown is shown at all),
     *   keyed per source group type.
     */
    operatorAllowlist?: Array<PropertyOperator>
    /**
     * Force single-select mode regardless of operator type
     * **/
    forceSingleSelect?: boolean
}

interface OperatorSelectProps extends Omit<LemonSelectProps<any>, 'options'> {
    operator: PropertyOperator
    operators: Array<PropertyOperator>
    onChange: (operator: PropertyOperator) => void
    startVisible?: LemonDropdownProps['startVisible']
}

function getRegexValidationError(operator: PropertyOperator, value: any): string | null {
    if (isOperatorRegex(operator)) {
        try {
            RE2JS.compile(value)
        } catch (error) {
            return formatRE2Error(error as Error, value)
        }
    }
    return null
}

function getValidationError(operator: PropertyOperator, value: any, property?: string): string | null {
    const regexErrorMessage = getRegexValidationError(operator, value)
    if (regexErrorMessage != null) {
        return regexErrorMessage
    }
    if (isOperatorRange(operator) && isNaN(value)) {
        let message = `Range operators only work with numeric values`
        if (dayjs(value).isValid()) {
            const propertyReference = property ? `property ${property}` : 'this property'
            message += `. If you'd like to compare dates and times, make sure ${propertyReference} is typed as DateTime in Data Management. You will then be able to use operators "before" and "after"`
        }
        return message
    }
    return null
}

export function OperatorValueSelect({
    type,
    propertyKey,
    operator,
    value,
    placeholder,
    endpoint,
    onChange,
    operatorSelectProps,
    propertyDefinitions = [],
    eventNames = [],
    addRelativeDateTimeOptions,
    groupTypeIndex = undefined,
    groupKeyNames,
    size,
    editable,
    startVisible,
    operatorAllowlist,
    forceSingleSelect,
}: OperatorValueSelectProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const semverTargetingEnabled = !!featureFlags[FEATURE_FLAGS.SEMVER_TARGETING]
    const lookupKey = type === PropertyFilterType.DataWarehousePersonProperty ? 'id' : 'name'
    const propertyDefinition = propertyDefinitions.find((pd) => pd[lookupKey] === propertyKey)

    const isCohortProperty = propertyKey === 'id' && type === PropertyFilterType.Cohort

    // DateTime properties should not default to Exact
    const isDateTimeProperty = propertyDefinition?.property_type == PropertyType.DateTime

    const isInitialOperator = !operator || operator == PropertyOperator.Exact

    let startingOperator = operator || PropertyOperator.Exact
    if (isInitialOperator) {
        if (isDateTimeProperty) {
            startingOperator = PropertyOperator.IsDateExact
        } else if (isCohortProperty) {
            startingOperator = PropertyOperator.In
        } else if (propertyKey === 'message' && type === PropertyFilterType.Log) {
            startingOperator = PropertyOperator.IContains
        }
    }

    const [currentOperator, setCurrentOperator] = useState(startingOperator)

    const [operators, setOperators] = useState([] as Array<PropertyOperator>)
    useEffect(() => {
        let propertyType = propertyDefinition?.property_type
        if (propertyKey === 'selector' || propertyKey === 'tag_name') {
            propertyType = PropertyType.Selector
        } else if (propertyKey === 'id' && type === PropertyFilterType.Cohort) {
            propertyType = PropertyType.Cohort
        } else if (type === PropertyFilterType.Flag) {
            propertyType = PropertyType.Flag
        } else if (propertyKey === 'assignee' && type === PropertyFilterType.ErrorTrackingIssue) {
            propertyType = PropertyType.Assignee
        } else if (propertyKey === 'first_seen' && type === PropertyFilterType.ErrorTrackingIssue) {
            propertyType = PropertyType.DateTime
        } else if (
            type === PropertyFilterType.Event &&
            propertyKey &&
            ['$exception_types', '$exception_values', '$exception_sources', '$exception_functions'].includes(
                propertyKey
            )
        ) {
            propertyType = PropertyType.StringArray
        }

        const operatorMapping: Record<string, string> = chooseOperatorMap(propertyType)

        let operators = (Object.keys(operatorMapping) as Array<PropertyOperator>).filter((op) => {
            // Filter out semver operators if feature flag is not enabled
            if (!semverTargetingEnabled && isOperatorSemver(op)) {
                return false
            }
            return !operatorAllowlist || operatorAllowlist.includes(op)
        })

        // Restrict message log property to only allow exact, is_not, contains, not contains, regex, and not regex operators
        if (propertyKey === 'message' && type === PropertyFilterType.Log) {
            operators = operators.filter((op) =>
                [
                    PropertyOperator.Exact,
                    PropertyOperator.IsNot,
                    PropertyOperator.IContains,
                    PropertyOperator.NotIContains,
                    PropertyOperator.Regex,
                    PropertyOperator.NotRegex,
                ].includes(op)
            )
        }

        // Restrict trace_id and span_id to only equals/not equals
        if ((propertyKey === 'trace_id' || propertyKey === 'span_id') && type === PropertyFilterType.Span) {
            operators = operators.filter((op) => [PropertyOperator.Exact, PropertyOperator.IsNot].includes(op))
        }

        // Restrict duration to equals, not equals, and numeric comparisons
        if (propertyKey === 'duration' && type === PropertyFilterType.Span) {
            operators = operators.filter((op) =>
                [
                    PropertyOperator.Exact,
                    PropertyOperator.IsNot,
                    PropertyOperator.GreaterThan,
                    PropertyOperator.GreaterThanOrEqual,
                    PropertyOperator.LessThan,
                    PropertyOperator.LessThanOrEqual,
                ].includes(op)
            )
        }

        // Restrict span name to string equality/contains operators
        if (propertyKey === 'name' && type === PropertyFilterType.Span) {
            operators = operators.filter((op) =>
                [
                    PropertyOperator.Exact,
                    PropertyOperator.IsNot,
                    PropertyOperator.IContains,
                    PropertyOperator.NotIContains,
                    PropertyOperator.Regex,
                    PropertyOperator.NotRegex,
                ].includes(op)
            )
        }

        // Restrict span kind and status_code (fixed int enums) to equality operators
        if ((propertyKey === 'kind' || propertyKey === 'status_code') && type === PropertyFilterType.Span) {
            operators = operators.filter((op) => [PropertyOperator.Exact, PropertyOperator.IsNot].includes(op))
        }

        setOperators(operators)
        if ((currentOperator !== operator && operators.includes(startingOperator)) || !propertyDefinition) {
            setCurrentOperator(startingOperator)
        } else if (!operators.includes(currentOperator) && propertyDefinition) {
            // Whenever the property type changes such that the operator is not compatible, we need to reset the operator
            // But, only if the propertyDefinition is available
            let defaultProperty = PropertyOperator.Exact
            if (isDateTimeProperty) {
                defaultProperty = PropertyOperator.IsDateExact
            } else if (propertyType === PropertyType.Cohort) {
                defaultProperty = PropertyOperator.In
            } else if (propertyKey === 'message' && type === PropertyFilterType.Log) {
                defaultProperty = PropertyOperator.IContains
            }
            setCurrentOperator(defaultProperty)
        }
    }, [propertyDefinition, propertyKey, operator, operatorAllowlist, semverTargetingEnabled]) // oxlint-disable-line react-hooks/exhaustive-deps

    const validationError = currentOperator && value ? getValidationError(currentOperator, value, propertyKey) : null

    return (
        <>
            <div data-attr="taxonomic-operator">
                {editable ? (
                    <OperatorSelect
                        operator={currentOperator || PropertyOperator.Exact}
                        operators={operators}
                        onChange={(newOperator: PropertyOperator) => {
                            setCurrentOperator(newOperator)
                            if (isOperatorCohort(newOperator)) {
                                onChange(newOperator, value || null)
                            } else if (isOperatorRange(newOperator) && isNaN(value as any)) {
                                // If the new operator is range and the value is not a number, we want to set the new value to null
                                onChange(newOperator, null)
                            } else if (
                                isOperatorDate(newOperator) &&
                                (Array.isArray(value) || !dayjs(value as string).isValid())
                            ) {
                                // If the new operator is date and the value is not a valid date, clear it
                                onChange(newOperator, null)
                            } else if (isOperatorFlag(newOperator)) {
                                onChange(newOperator, newOperator)
                            } else if (isOperatorFlag(currentOperator || PropertyOperator.Exact)) {
                                onChange(newOperator, null)
                            } else if (
                                isOperatorMulti(currentOperator || PropertyOperator.Exact) &&
                                !isOperatorMulti(newOperator) &&
                                Array.isArray(value)
                            ) {
                                onChange(newOperator, value[0])
                            } else if (value) {
                                onChange(newOperator, value)
                            }
                        }}
                        {...operatorSelectProps}
                        size={size}
                        startVisible={startVisible}
                    />
                ) : (
                    <span>{allOperatorsToHumanName(currentOperator)} </span>
                )}
            </div>
            {!isOperatorFlag(currentOperator || PropertyOperator.Exact) && type && propertyKey && (
                <div
                    // High flex-grow for proper sizing within TaxonomicPropertyFilter
                    className="shrink grow-[1000] min-w-[10rem] overflow-hidden"
                    data-attr="taxonomic-value-select"
                >
                    {type === PropertyFilterType.Span && (propertyKey === 'kind' || propertyKey === 'status_code') ? (
                        editable ? (
                            <SpanEnumValueSelect
                                options={propertyKey === 'kind' ? SPAN_KIND_OPTIONS : STATUS_CODE_OPTIONS}
                                value={value}
                                isMultiSelect={
                                    forceSingleSelect
                                        ? false
                                        : isOperatorMulti(currentOperator || PropertyOperator.Exact)
                                }
                                size={size}
                                onChange={(newValue) => onChange(currentOperator || PropertyOperator.Exact, newValue)}
                            />
                        ) : (
                            <span>
                                {(Array.isArray(value) ? value : value == null ? [] : [value])
                                    .map((v) => String(v))
                                    .join(' or ')}
                            </span>
                        )
                    ) : (
                        <PropertyValue
                            type={type}
                            key={propertyKey}
                            propertyKey={propertyKey}
                            endpoint={endpoint}
                            operator={currentOperator || PropertyOperator.Exact}
                            placeholder={placeholder}
                            value={value}
                            eventNames={eventNames}
                            onSet={(newValue: string | number | string[] | null) => {
                                onChange(currentOperator || PropertyOperator.Exact, newValue)
                            }}
                            // open automatically only if new filter
                            autoFocus={!isMobile() && value === null}
                            addRelativeDateTimeOptions={addRelativeDateTimeOptions}
                            groupTypeIndex={groupTypeIndex}
                            groupKeyNames={groupKeyNames}
                            editable={editable}
                            size={size}
                            forceSingleSelect={forceSingleSelect}
                            validationError={validationError}
                        />
                    )}
                </div>
            )}
            {validationError && (
                <div className="basis-full w-full">
                    <LemonBanner type="warning" hideIcon>
                        {validationError}
                        {isOperatorRegex(currentOperator) && (
                            <>
                                {' '}
                                <Link to={RE2_DOCS_LINK} target="_blank">
                                    Learn more
                                </Link>
                            </>
                        )}
                    </LemonBanner>
                </div>
            )}
        </>
    )
}

function toOption(op: PropertyOperator): { label: JSX.Element; value: PropertyOperator } {
    return {
        label: <span className="operator-value-option">{allOperatorsMapping[op || PropertyOperator.Exact]}</span>,
        value: op || PropertyOperator.Exact,
    }
}

export function OperatorSelect({
    operator,
    operators,
    onChange,
    className,
    size,
    startVisible,
}: OperatorSelectProps): JSX.Element {
    const hasSemver = operators.some(isOperatorSemver)
    const options: LemonSelectSection<PropertyOperator>[] | { label: JSX.Element; value: PropertyOperator }[] =
        hasSemver
            ? [
                  ...(operators.some((op) => !isOperatorSemver(op))
                      ? [{ options: operators.filter((op) => !isOperatorSemver(op)).map(toOption) }]
                      : []),
                  {
                      title: 'Semver operators',
                      footer: (
                          <div className="mx-2 my-1">
                              <Link
                                  to="https://posthog.com/docs/data/property-filters#semver-operators"
                                  target="_blank"
                                  className="text-xs"
                              >
                                  Learn more
                              </Link>
                          </div>
                      ),
                      options: operators.filter(isOperatorSemver).map(toOption),
                  },
              ]
            : operators.map(toOption)

    return (
        <LemonSelect
            options={options}
            value={operator || '='}
            placeholder="Property key"
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-start"
            fullWidth
            onChange={(op) => {
                op && onChange(op)
            }}
            className={className}
            size={size}
            menu={{
                closeParentPopoverOnClickInside: false,
                ...(hasSemver ? { className: '!max-h-[400px]' } : {}),
            }}
            startVisible={startVisible}
        />
    )
}
