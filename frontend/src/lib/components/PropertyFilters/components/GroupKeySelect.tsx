import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { isOperatorMulti } from 'lib/utils/operators'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'

import type { GroupTypeIndex, PropertyFilterValue, PropertyOperator } from '~/types'

import { GroupInfoCard, GroupKeyFilterTooltip } from './GroupKeyFilterTooltip'
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
    const { groups, groupsLoading, resolvedNames, searchQuery } = useValues(logic)
    const { setSearchQuery } = useActions(logic)
    const isMultiSelect = forceSingleSelect ? false : operator && isOperatorMulti(operator)

    const options = useMemo(() => {
        const optionMap = new Map<string, LemonInputSelectOption>()
        for (const group of groups) {
            optionMap.set(group.group_key, {
                key: group.group_key,
                label: groupDisplayId(group.group_key, group.group_properties),
                tooltip: <GroupInfoCard group={group} />,
            })
        }
        for (const v of currentValues) {
            if (!optionMap.has(v)) {
                optionMap.set(v, {
                    key: v,
                    label: resolvedNames[v] ?? v,
                    tooltip: (
                        <GroupKeyFilterTooltip
                            groupTypeIndex={groupTypeIndex}
                            groupKey={v}
                            fallbackLabel={resolvedNames[v] ?? v}
                        />
                    ),
                })
            }
        }
        return Array.from(optionMap.values())
    }, [groups, currentValues, resolvedNames, groupTypeIndex])

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
