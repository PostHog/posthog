import { useActions, useValues } from 'kea'
import { useId, useMemo } from 'react'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { isOperatorMulti } from 'lib/utils'

import type { PropertyFilterValue, PropertyOperator } from '~/types'

import { distinctIdSelectLogic } from './distinctIdSelectLogic'

export interface DistinctIdSelectProps {
    value: PropertyFilterValue
    operator: PropertyOperator
    onChange: (value: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
    autoFocus?: boolean
    forceSingleSelect?: boolean
}

export function DistinctIdSelect({
    value,
    operator,
    onChange,
    size,
    autoFocus = false,
    forceSingleSelect = false,
}: DistinctIdSelectProps): JSX.Element {
    const instanceKey = useId()
    const currentValues = useMemo(
        () => (value === null || value === undefined ? [] : Array.isArray(value) ? value.map(String) : [String(value)]),
        [value]
    )

    const logic = distinctIdSelectLogic({ instanceKey, value: currentValues })
    const { mergedOptions, personsLoading, searchQuery } = useValues(logic)
    const { setSearchQuery } = useActions(logic)
    const isMultiSelect = forceSingleSelect ? false : operator && isOperatorMulti(operator)

    return (
        <LemonInputSelect
            data-attr="prop-val"
            loading={personsLoading}
            value={currentValues}
            mode={isMultiSelect ? 'multiple' : 'single'}
            singleValueAsSnack
            allowCustomValues
            onChange={(nextVal) => (isMultiSelect ? onChange(nextVal) : onChange(nextVal[0] ?? null))}
            onInputChange={(input) => {
                const trimmed = input.trim()
                if (trimmed !== searchQuery) {
                    setSearchQuery(trimmed)
                }
            }}
            placeholder="Search by name, email, or distinct ID…"
            size={size}
            autoFocus={autoFocus}
            disableFiltering
            options={mergedOptions.map((opt) => ({
                key: opt.key,
                label: opt.label,
                labelComponent: (
                    <span className="flex flex-col">
                        <span className="truncate">{opt.key}</span>
                        {opt.label !== opt.key && <span className="text-muted text-xs truncate">{opt.label}</span>}
                    </span>
                ),
            }))}
        />
    )
}
