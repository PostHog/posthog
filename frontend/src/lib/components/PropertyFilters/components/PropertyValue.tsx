import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconFeatures, IconRefresh } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from '@posthog/products-error-tracking/frontend/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '@posthog/products-error-tracking/frontend/components/Assignee/AssigneeSelect'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import { GroupKeySelect } from 'lib/components/PropertyFilters/components/GroupKeySelect'
import { PropertyFilterBetween } from 'lib/components/PropertyFilters/components/PropertyFilterBetween'
import { PropertyFilterDatePicker } from 'lib/components/PropertyFilters/components/PropertyFilterDatePicker'
import { propertyValueLogic } from 'lib/components/PropertyFilters/components/propertyValueLogic'
import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import {
    formatDate,
    isOperatorBetween,
    isOperatorDate,
    isOperatorFlag,
    isOperatorMulti,
    isOperatorRegex,
    toString,
} from 'lib/utils'

import {
    PROPERTY_FILTER_TYPES_WITH_ALL_TIME_SUGGESTIONS,
    PROPERTY_FILTER_TYPES_WITH_TEMPORAL_SUGGESTIONS,
    propertyDefinitionsModel,
} from '~/models/propertyDefinitionsModel'
import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { GroupTypeIndex, PropertyFilterType, PropertyFilterValue, PropertyOperator, PropertyType } from '~/types'

export interface PropertyValueProps {
    propertyKey: string
    type: PropertyFilterType
    endpoint?: string // Endpoint to fetch options from
    placeholder?: string
    onSet: CallableFunction
    value?: PropertyFilterValue
    operator: PropertyOperator
    autoFocus?: boolean
    eventNames?: string[]
    addRelativeDateTimeOptions?: boolean
    inputClassName?: string
    groupTypeIndex?: GroupTypeIndex
    groupKeyNames?: Record<string, string>
    size?: 'xsmall' | 'small' | 'medium'
    editable?: boolean
    preloadValues?: boolean
    forceSingleSelect?: boolean
    validationError?: string | null
    showInlineValidationErrors?: boolean
}

export function PropertyValue({
    propertyKey,
    type,
    endpoint = undefined,
    placeholder = undefined,
    onSet,
    value,
    operator,
    size,
    autoFocus = false,
    eventNames = [],
    addRelativeDateTimeOptions = false,
    inputClassName = undefined,
    groupTypeIndex = undefined,
    groupKeyNames,
    editable = true,
    preloadValues = false,
    forceSingleSelect = false,
    validationError = null,
    showInlineValidationErrors = false,
}: PropertyValueProps): JSX.Element {
    const { formatPropertyValueForDisplay, describeProperty, options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const propertyOptions = options[propertyKey]
    const isFlagDependencyProperty = type === PropertyFilterType.Flag

    const isMultiSelect = forceSingleSelect ? false : operator && isOperatorMulti(operator)
    const isDateTimeProperty = operator && isOperatorDate(operator)
    const isBetweenProperty = operator && isOperatorBetween(operator)
    const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(type)
    const { isRefreshing } = useValues(propertyValueLogic({ propertyKey, type: propertyDefinitionType }))

    const isDurationProperty =
        propertyKey && describeProperty(propertyKey, propertyDefinitionType) === PropertyType.Duration

    // Assignee values come from membersLogic/rolesLogic, not from the property values API
    const isAssigneeProperty =
        propertyKey && describeProperty(propertyKey, propertyDefinitionType) === PropertyType.Assignee

    const isNumericProperty =
        propertyKey && describeProperty(propertyKey, propertyDefinitionType) === PropertyType.Numeric
    const shouldRestrictToNumericInput = isNumericProperty && !isOperatorRegex(operator)

    const isGroupKeyProperty = propertyKey === '$group_key' && groupTypeIndex != null

    // TODO: Add semver input validation when a semver operator is selected.
    // This will require detecting isOperatorSemver(operator) and validating the input
    // matches semver format (e.g., "1.2.3", "1.2.3-alpha", etc.)

    // we first load a set of suggested values when there is no user input yet to avoid
    // options jumping around as the user types, we keep the initially loaded options
    // in state and show those first, then any new options based on user input after
    const [initialSuggestedValues, setInitialSuggestedValues] = useState<{
        set: Set<string>
        orderedKeys: string[]
    }>({ set: new Set(), orderedKeys: [] })
    const currentSearchInput = useRef<string>('')

    const load = useCallback(
        (newInput: string | undefined): void => {
            currentSearchInput.current = newInput || ''
            loadPropertyValues({
                endpoint,
                type: propertyDefinitionType,
                newInput,
                propertyKey,
                eventNames,
                properties: [],
            })
        },
        [loadPropertyValues, endpoint, propertyDefinitionType, propertyKey, eventNames]
    )

    const setValue = (newValue: PropertyValueProps['value']): void => onSet(newValue)

    // preload values if preloadValues prop is set
    useEffect(() => {
        if (
            !isGroupKeyProperty &&
            !isAssigneeProperty &&
            preloadValues &&
            propertyOptions?.status !== 'loading' &&
            propertyOptions?.status !== 'loaded'
        ) {
            load('')
        }
    }, [preloadValues, load, propertyOptions?.status, isGroupKeyProperty, isAssigneeProperty])

    // load options when propertyKey changes, unless it's a date/time property (since those don't have options to load)
    useEffect(() => {
        if (
            !isGroupKeyProperty &&
            !isAssigneeProperty &&
            !isDateTimeProperty &&
            propertyOptions?.status !== 'loading' &&
            propertyOptions?.status !== 'loaded'
        ) {
            load('')
        }
    }, [propertyKey, isDateTimeProperty, isGroupKeyProperty, isAssigneeProperty, load, propertyOptions?.status])

    // set initial suggested values when options are loaded, but only if there is no search input
    // (to avoid overwriting suggestions based on search input)
    useEffect(() => {
        if (propertyOptions?.status === 'loaded' && propertyOptions?.values && currentSearchInput.current === '') {
            const newKeys = propertyOptions.values.map((v) => toString(v.name))
            setInitialSuggestedValues((prev) => {
                // Merge new keys into existing ones so that values already shown are never removed
                // from under the user's cursor when a background refresh arrives with a different list.
                const merged = [...prev.orderedKeys]
                const existingSet = new Set(prev.orderedKeys)
                for (const key of newKeys) {
                    if (!existingSet.has(key)) {
                        merged.push(key)
                        existingSet.add(key)
                    }
                }
                return { set: existingSet, orderedKeys: merged }
            })
        }
    }, [propertyOptions?.status, propertyOptions?.values])

    // reset initial suggested values when propertyKey changes
    useEffect(() => {
        setInitialSuggestedValues({ set: new Set(), orderedKeys: [] })
    }, [propertyKey])

    // show suggested values first, then any other available options that aren't in the suggested list
    const displayOptions = useMemo(() => {
        const options = propertyOptions?.values || []
        if (initialSuggestedValues.set.size === 0) {
            return options
        }

        // map options by name
        const allOptionsMap = new Map<string, (typeof options)[0]>()
        for (const option of options) {
            allOptionsMap.set(toString(option.name), option)
        }

        const suggestedOptions: typeof options = []
        const otherOptions: typeof options = []

        // build suggested options in order of their name, and remove them from the all options map
        for (const key of initialSuggestedValues.orderedKeys) {
            const existingOption = allOptionsMap.get(key)
            if (existingOption) {
                suggestedOptions.push(existingOption)
                allOptionsMap.delete(key)
            } else {
                suggestedOptions.push({ name: key } as (typeof options)[0])
            }
        }

        // built other options from what's left in the all options map
        for (const option of allOptionsMap.values()) {
            otherOptions.push(option)
        }

        return [...suggestedOptions, ...otherOptions]
    }, [propertyOptions?.values, initialSuggestedValues])

    const onSearchTextChange = (newInput: string): void => {
        const trimmedInput = newInput.trim()
        if (trimmedInput !== currentSearchInput.current && !(operator && isOperatorFlag(operator))) {
            load(trimmedInput)
        }
    }

    if (isAssigneeProperty) {
        // Kludge: when switching between operators the value isn't always JSON
        const parseAssignee = (value: PropertyFilterValue): ErrorTrackingIssueAssignee | null => {
            try {
                return JSON.parse(value as string)
            } catch {
                return null
            }
        }

        const assignee = value ? parseAssignee(value) : null

        return editable ? (
            <AssigneeSelect assignee={assignee} onChange={(value) => setValue(JSON.stringify(value))}>
                {(displayAssignee) => (
                    <LemonButton fullWidth type="secondary" size={size}>
                        <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Choose user" />
                    </LemonButton>
                )}
            </AssigneeSelect>
        ) : (
            <AssigneeResolver assignee={assignee}>
                {({ assignee }) => (
                    <>
                        <AssigneeIconDisplay assignee={assignee} />
                        <AssigneeLabelDisplay assignee={assignee} />
                    </>
                )}
            </AssigneeResolver>
        )
    }

    if (isGroupKeyProperty && editable) {
        return (
            <GroupKeySelect
                value={value ?? null}
                groupTypeIndex={groupTypeIndex}
                operator={operator}
                onChange={setValue}
                size={size}
                autoFocus={autoFocus}
                forceSingleSelect={forceSingleSelect}
            />
        )
    }

    const formattedValues = (value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]).map(
        (label) => String(formatPropertyValueForDisplay(propertyKey, label, propertyDefinitionType, groupTypeIndex))
    )

    if (!editable) {
        if (isGroupKeyProperty && groupKeyNames) {
            const rawValues = (value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]).map(
                String
            )
            const displayValues = rawValues.map((key) => groupKeyNames[key] || key)
            return <>{displayValues.join(' or ')}</>
        }
        return <>{formattedValues.join(' or ')}</>
    }

    if (isDurationProperty) {
        return <DurationPicker autoFocus={autoFocus} value={value as number} onChange={setValue} />
    }

    if (isBetweenProperty) {
        return <PropertyFilterBetween value={value ?? null} onSet={setValue} size={size} />
    }

    if (isDateTimeProperty) {
        if (!addRelativeDateTimeOptions || operator === PropertyOperator.IsDateExact) {
            return (
                <PropertyFilterDatePicker
                    autoFocus={autoFocus}
                    operator={operator}
                    value={value as string | number | null}
                    setValue={setValue}
                />
            )
        }

        return (
            <DateFilter
                dateFrom={String(value)}
                onChange={setValue}
                max={10000}
                isFixedDateMode
                dateOptions={[
                    {
                        key: 'Last 24 hours',
                        values: ['-24h'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(24, 'h')),
                        defaultInterval: 'hour',
                    },
                    {
                        key: 'Last 7 days',
                        values: ['-7d'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(7, 'd')),
                        defaultInterval: 'day',
                    },
                    {
                        key: 'Last 14 days',
                        values: ['-14d'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(14, 'd')),
                        defaultInterval: 'day',
                    },
                ]}
                size="medium"
                makeLabel={(_, startOfRange) => (
                    <span className="hide-when-small">
                        Matches all values {operator === PropertyOperator.IsDateBefore ? 'before' : 'after'}{' '}
                        {startOfRange} if evaluated today.
                    </span>
                )}
            />
        )
    }

    function formatLabelContent(value: any): JSX.Element {
        const name = toString(value)
        if (name === '') {
            return <i>(empty string)</i>
        }
        if (isFlagDependencyProperty && typeof value === 'boolean') {
            return <code>{name}</code>
        }
        return <>{formatPropertyValueForDisplay(propertyKey, name, propertyDefinitionType, groupTypeIndex)}</>
    }

    // Disable comma splitting for user agent properties that contain commas in their values
    const isUserAgentProperty = ['$raw_user_agent', '$initial_raw_user_agent', '$user_agent'].includes(propertyKey)

    const suggestionsLabel = PROPERTY_FILTER_TYPES_WITH_TEMPORAL_SUGGESTIONS.includes(type)
        ? 'Suggested values (last 7 days)'
        : PROPERTY_FILTER_TYPES_WITH_ALL_TIME_SUGGESTIONS.includes(type)
          ? 'Suggested values'
          : null
    const refreshDisabledReason =
        propertyOptions?.status === 'loading' ? 'Loading values…' : isRefreshing ? 'Refreshing values…' : undefined
    const titleNode = suggestionsLabel ? (
        <span className="flex justify-between items-center gap-4">
            {suggestionsLabel}
            <LemonButton
                size="xsmall"
                icon={<IconRefresh />}
                tooltip="Refresh values"
                disabledReason={refreshDisabledReason}
                onClick={() =>
                    loadPropertyValues({
                        endpoint,
                        type: propertyDefinitionType,
                        newInput: currentSearchInput.current || undefined,
                        propertyKey,
                        eventNames,
                        properties: [],
                        refresh: 'force_blocking',
                    })
                }
                noPadding
            />
        </span>
    ) : undefined

    return (
        <div>
            <LemonInputSelect
                className={inputClassName}
                data-attr="prop-val"
                loading={propertyOptions?.status === 'loading' || isRefreshing}
                value={formattedValues}
                mode={isMultiSelect ? 'multiple' : 'single'}
                singleValueAsSnack
                allowCustomValues={propertyOptions?.allowCustomValues ?? true}
                inputTransform={
                    shouldRestrictToNumericInput
                        ? (input: string) => {
                              // Only allow numeric characters, decimal point, and +/- signs
                              return input.replace(/[^0-9+\-.]/g, '')
                          }
                        : undefined
                }
                onChange={(nextVal) => {
                    const newValues = nextVal.filter((v) => !formattedValues.includes(String(v)))
                    if (newValues.length > 0) {
                        const availableValues = new Set(displayOptions.map((o) => toString(o.name)))
                        const fromSuggestion = newValues.every((v) => availableValues.has(toString(v)))

                        posthog.capture('property_value_selected', {
                            property_key: propertyKey,
                            property_type: type,
                            from_suggestion: fromSuggestion,
                            options_count: displayOptions.length,
                            had_search_input: currentSearchInput.current !== '',
                        })
                    }
                    isMultiSelect ? setValue(nextVal) : setValue(nextVal[0])
                }}
                onInputChange={onSearchTextChange}
                placeholder={placeholder}
                size={size}
                disableCommaSplitting={isUserAgentProperty}
                status={validationError ? 'danger' : 'default'}
                title={titleNode}
                popoverClassName="max-w-200"
                options={displayOptions.map(({ name: _name }, index) => {
                    const name = toString(_name)
                    const isSuggested = initialSuggestedValues.set.has(name)
                    return {
                        key: name,
                        label: name,
                        value: isFlagDependencyProperty ? _name : undefined, // Preserve original type for flags
                        labelComponent: (
                            <span
                                key={name}
                                data-attr={'prop-val-' + index}
                                className="ph-no-capture flex items-center gap-1.5"
                                title={name}
                            >
                                {formatLabelContent(isFlagDependencyProperty ? _name : name)}
                                {isSuggested && currentSearchInput.current && (
                                    <Tooltip title="Suggested value">
                                        <IconFeatures className="text-muted shrink-0 w-4 h-4" />
                                    </Tooltip>
                                )}
                            </span>
                        ),
                    }
                })}
            />
            {showInlineValidationErrors && validationError && (
                <div className="text-danger flex items-center gap-1 text-sm mt-1">
                    <IconErrorOutline className="text-xl shrink-0" /> {validationError}
                </div>
            )}
        </div>
    )
}
