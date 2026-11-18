import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import {
    buildBIFilterOptionsQuery,
    getBIFilterValidationError,
    isDateTimeBIField,
} from 'products/business_intelligence/frontend/biEditorTypes'
import { biFilterValuesLogic } from 'products/business_intelligence/frontend/biFilterValuesLogic'

import { getBIFilterLabel } from './biFilterSummary'
import { getBIMemberOptions } from './biMemberAliases'

export function BIFilterValueInput({ index }: { index: number }): JSX.Element | null {
    const { config } = useValues(biEditorLogic)
    const { setFilterValue, updateFilter } = useActions(biEditorLogic)
    const filter = config.filters[index]
    const [focused, setFocused] = useState(false)
    const valuesLogic = biFilterValuesLogic({
        query: buildBIFilterOptionsQuery(config, index),
        active: focused,
        config,
    })
    const { options, optionsLoading, optionsError, hasMore, search } = useValues(valuesLogic)
    const { loadOptions, setSearch, loadMore } = useActions(valuesLogic)
    if (!filter || ['last_7_days', 'is_set', 'is_not_set', 'custom'].includes(filter.operator)) {
        return null
    }
    const validationError = getBIFilterValidationError(filter)
    const multiple = filter.operator === 'in' || filter.operator === 'not_in'
    if (multiple || (!isDateTimeBIField(filter.field) && filter.operator !== 'between')) {
        return (
            <div
                className="flex min-w-0 flex-col gap-1"
                onInput={(event) => {
                    if (!multiple && event.target instanceof HTMLInputElement && event.target.value === '') {
                        setFilterValue(index, '')
                    }
                }}
            >
                <LemonInputSelect
                    mode={multiple ? 'multiple' : 'single'}
                    value={filter.values ?? (multiple || !filter.value ? [] : [filter.value])}
                    options={
                        multiple || filter.operator === 'equals' || filter.operator === 'not_equals'
                            ? getBIMemberOptions(
                                  config,
                                  filter.field,
                                  options ?? [],
                                  filter.values ?? (filter.value ? [filter.value] : []),
                                  search
                              )
                            : (options ?? []).map((value) => ({ key: value, label: value }))
                    }
                    loading={optionsLoading && options === null}
                    status={validationError ? 'danger' : 'default'}
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    onChange={(values) =>
                        updateFilter(index, multiple ? { values } : { values, value: values[0] ?? '' })
                    }
                    onInputChange={setSearch}
                    disableFiltering
                    placeholder={multiple ? (filter.operator === 'in' ? 'All values' : 'No excluded values') : 'Value'}
                    title={`Values for ${getBIFilterLabel(filter)}`}
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
                ) : hasMore ? (
                    <LemonButton size="xsmall" onClick={loadMore} loading={optionsLoading}>
                        Load more values
                    </LemonButton>
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
                const label = `${getBIFilterLabel(filter)} filter ${isRange ? bound : 'value'}`
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
