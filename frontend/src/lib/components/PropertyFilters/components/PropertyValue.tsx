import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconFeatures } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from '@posthog/products-error-tracking/frontend/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '@posthog/products-error-tracking/frontend/components/Assignee/AssigneeSelect'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import { PropertyFilterBetween } from 'lib/components/PropertyFilters/components/PropertyFilterBetween'
import { PropertyFilterDatePicker } from 'lib/components/PropertyFilters/components/PropertyFilterDatePicker'
import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { formatDate, isOperatorBetween, isOperatorDate, isOperatorFlag, isOperatorMulti, toString } from 'lib/utils'

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
    size?: 'xsmall' | 'small' | 'medium'
    editable?: boolean
    preloadValues?: boolean
    forceSingleSelect?: boolean
    validationError?: string | null
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
    editable = true,
    preloadValues = false,
    forceSingleSelect = false,
    validationError = null,
}: PropertyValueProps): JSX.Element {
    const { formatPropertyValueForDisplay, describeProperty, options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const propertyOptions = options[propertyKey]
    const isFlagDependencyProperty = type === PropertyFilterType.Flag

    const isMultiSelect = forceSingleSelect ? false : operator && isOperatorMulti(operator)
    const isDateTimeProperty = operator && isOperatorDate(operator)
    const isBetweenProperty = operator && isOperatorBetween(operator)
    const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(type)

    const isDurationProperty =
        propertyKey && describeProperty(propertyKey, propertyDefinitionType) === PropertyType.Duration

    const isAssigneeProperty =
        propertyKey && describeProperty(propertyKey, propertyDefinitionType) === PropertyType.Assignee

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
        if (preloadValues && propertyOptions?.status !== 'loading' && propertyOptions?.status !== 'loaded') {
            load('')
        }
    }, [preloadValues, load, propertyOptions?.status])

    // load options when propertyKey changes, unless it's a date/time property (since those don't have options to load)
    useEffect(() => {
        if (!isDateTimeProperty && propertyOptions?.status !== 'loading' && propertyOptions?.status !== 'loaded') {
            load('')
        }
    }, [propertyKey, isDateTimeProperty, load, propertyOptions?.status])

    // set initial suggested values when options are loaded, but only if there is no search input
    // (to avoid overwriting suggestions based on search input)
    useEffect(() => {
        if (propertyOptions?.status === 'loaded' && propertyOptions?.values && currentSearchInput.current === '') {
            const orderedKeys = propertyOptions.values.map((v) => toString(v.name))
            setInitialSuggestedValues({
                set: new Set(orderedKeys),
                orderedKeys,
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

    const formattedValues = (value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]).map(
        (label) => String(formatPropertyValueForDisplay(propertyKey, label, propertyDefinitionType, groupTypeIndex))
    )

    if (!editable) {
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

    return (
        <LemonInputSelect
            className={inputClassName}
            data-attr="prop-val"
            loading={propertyOptions?.status === 'loading'}
            value={formattedValues}
            mode={isMultiSelect ? 'multiple' : 'single'}
            allowCustomValues={propertyOptions?.allowCustomValues ?? true}
            onChange={(nextVal) => (isMultiSelect ? setValue(nextVal) : setValue(nextVal[0]))}
            onInputChange={onSearchTextChange}
            placeholder={placeholder}
            size={size}
            disableCommaSplitting={isUserAgentProperty}
            status={validationError ? 'danger' : 'default'}
            title={
                PROPERTY_FILTER_TYPES_WITH_TEMPORAL_SUGGESTIONS.includes(type)
                    ? 'Suggested values (last 7 days)'
                    : PROPERTY_FILTER_TYPES_WITH_ALL_TIME_SUGGESTIONS.includes(type)
                      ? 'Suggested values'
                      : undefined
            }
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
    )
}
