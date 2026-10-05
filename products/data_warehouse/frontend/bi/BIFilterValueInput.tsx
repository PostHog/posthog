import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { biEditorLogic } from 'scenes/data-warehouse/editor/bi/biEditorLogic'
import {
    buildBIFilterOptionsQuery,
    getBIFilterValidationError,
    isDateTimeBIField,
} from 'scenes/data-warehouse/editor/bi/biEditorTypes'

import { biFilterValuesLogic } from './biFilterValuesLogic'

export function BIFilterValueInput({ index }: { index: number }): JSX.Element | null {
    const { config } = useValues(biEditorLogic)
    const { setFilterValue, updateFilter } = useActions(biEditorLogic)
    const filter = config.filters[index]
    const [focused, setFocused] = useState(false)
    const valuesLogic = biFilterValuesLogic({ query: buildBIFilterOptionsQuery(config, index), active: focused })
    const { options, optionsLoading, optionsError } = useValues(valuesLogic)
    const { loadOptions } = useActions(valuesLogic)
    if (!filter || ['last_7_days', 'is_set', 'is_not_set', 'custom'].includes(filter.operator)) {
        return null
    }
    const validationError = getBIFilterValidationError(filter)
    if (filter.operator === 'in' || filter.operator === 'not_in') {
        return (
            <div className="flex min-w-0 flex-col gap-1">
                <LemonInputSelect
                    mode="multiple"
                    value={filter.values ?? []}
                    options={(options ?? []).map((value) => ({ key: value, label: value || '(empty string)' }))}
                    loading={optionsLoading}
                    status={validationError ? 'danger' : 'default'}
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    onChange={(values) => updateFilter(index, { values })}
                    placeholder={filter.operator === 'in' ? 'All values' : 'No excluded values'}
                    title={`Values for ${filter.field.name}`}
                    allowCustomValues
                    disableCommaSplitting
                    bulkActions="clear-all"
                    size="small"
                    className="[&_input]:min-w-20"
                    data-attr="bi-filter-values"
                    fullWidth
                />
                {validationError && (
                    <span role="alert" className="text-xs text-danger">
                        {validationError}
                    </span>
                )}
                {optionsError ? (
                    <div className="text-xs text-danger">
                        <span>Could not load suggestions. You can still enter values.</span>
                        <LemonButton size="xsmall" onClick={() => loadOptions()} loading={optionsLoading}>
                            Retry
                        </LemonButton>
                    </div>
                ) : options?.length === 100 ? (
                    <span className="text-xs text-tertiary">Showing 100 suggestions. Type to add another value.</span>
                ) : null}
            </div>
        )
    }
    const isRange = filter.operator === 'between'
    return (
        <div className="flex min-w-0 flex-col gap-1">
            {(isRange ? (['from', 'to'] as const) : (['from'] as const)).map((bound) => {
                const value = bound === 'from' ? filter.value : (filter.valueTo ?? '')
                const onChange = (next: string): void => {
                    if (bound === 'from') {
                        setFilterValue(index, next)
                    } else {
                        updateFilter(index, { valueTo: next })
                    }
                }
                const label = `${filter.field.name} filter ${isRange ? bound : 'value'}`
                return (
                    <div key={bound} className="flex min-w-0 flex-col gap-1">
                        {isRange ? (
                            <span className="text-xs text-secondary">
                                {bound === 'from' ? 'From (inclusive)' : 'To (inclusive)'}
                            </span>
                        ) : null}
                        {isDateTimeBIField(filter.field) ? (
                            <LemonCalendarSelectInput
                                value={value && dayjs(value).isValid() ? dayjs(value) : null}
                                onChange={(date) =>
                                    onChange(
                                        date?.format(
                                            filter.field.type === 'datetime' ? 'YYYY-MM-DD HH:mm:ss' : 'YYYY-MM-DD'
                                        ) ?? ''
                                    )
                                }
                                granularity={filter.field.type === 'datetime' ? 'minute' : 'day'}
                                format={filter.field.type === 'datetime' ? 'MMM D, YYYY HH:mm' : 'MMM D, YYYY'}
                                use24HourFormat
                                clearable
                                placeholder={
                                    isRange ? (bound === 'from' ? 'No lower bound' : 'No upper bound') : 'Select date'
                                }
                                buttonProps={{ size: 'small', 'aria-label': label, fullWidth: true }}
                            />
                        ) : (
                            <LemonInput
                                value={value}
                                onChange={onChange}
                                placeholder={isRange ? (bound === 'from' ? 'No minimum' : 'No maximum') : 'Value'}
                                aria-label={label}
                                size="small"
                                status={validationError ? 'danger' : 'default'}
                            />
                        )}
                    </div>
                )
            })}
            {validationError && (
                <span role="alert" className="text-xs text-danger">
                    {validationError}
                </span>
            )}
        </div>
    )
}
