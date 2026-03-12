import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { isOperatorMulti } from 'lib/utils'

import type { GroupTypeIndex, PropertyFilterValue, PropertyOperator } from '~/types'

import { groupKeySelectLogic } from './groupKeySelectLogic'

export interface GroupKeySelectProps {
    value: PropertyFilterValue
    groupTypeIndex: GroupTypeIndex
    operator: PropertyOperator
    onChange: (value: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
    autoFocus?: boolean
    forceSingleSelect?: boolean
}

export function GroupKeySelect({
    value,
    groupTypeIndex,
    operator,
    onChange,
    size,
    autoFocus = false,
    forceSingleSelect = false,
}: GroupKeySelectProps): JSX.Element {
    const currentValues = useMemo(
        () => (value === null || value === undefined ? [] : Array.isArray(value) ? value.map(String) : [String(value)]),
        [value]
    )

    const logic = groupKeySelectLogic({ groupTypeIndex, value: currentValues })
    const { groupOptions, groupsLoading, resolvedNames, searchQuery } = useValues(logic)
    const { setSearchQuery } = useActions(logic)
    const isMultiSelect = forceSingleSelect ? false : operator && isOperatorMulti(operator)

    const options = useMemo(() => {
        const optionMap = new Map<string, { key: string; label: string }>()
        for (const opt of groupOptions) {
            optionMap.set(opt.key, opt)
        }
        for (const v of currentValues) {
            if (!optionMap.has(v)) {
                optionMap.set(v, { key: v, label: resolvedNames[v] ?? v })
            }
        }
        return Array.from(optionMap.values())
    }, [groupOptions, currentValues, resolvedNames])

    return (
        <LemonInputSelect
            data-attr="prop-val"
            loading={groupsLoading}
            value={currentValues}
            mode={isMultiSelect ? 'multiple' : 'single'}
            singleValueAsSnack
            allowCustomValues
            onChange={(nextVal) => (isMultiSelect ? onChange(nextVal) : onChange(nextVal[0]))}
            onInputChange={(input) => {
                const trimmed = input.trim()
                if (trimmed !== searchQuery) {
                    setSearchQuery(trimmed)
                }
            }}
            placeholder="Search groups by name..."
            size={size}
            autoFocus={autoFocus}
            disableFiltering
            options={options}
        />
    )
}
