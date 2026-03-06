import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import api from 'lib/api'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { isOperatorMulti } from 'lib/utils'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { teamLogic } from 'scenes/teamLogic'

import { Group } from '~/types'
import type { GroupTypeIndex, PropertyFilterValue, PropertyOperator } from '~/types'

export interface GroupKeySelectProps {
    value: PropertyFilterValue
    groupTypeIndex: GroupTypeIndex
    operator: PropertyOperator
    onChange: (value: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
    editable?: boolean
    autoFocus?: boolean
    forceSingleSelect?: boolean
}

interface GroupOption {
    key: string
    label: string
}

export function GroupKeySelect({
    value,
    groupTypeIndex,
    operator,
    onChange,
    size,
    editable = true,
    autoFocus = false,
    forceSingleSelect = false,
}: GroupKeySelectProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const isMultiSelect = forceSingleSelect ? false : operator && isOperatorMulti(operator)

    const [searchOptions, setSearchOptions] = useState<GroupOption[]>([])
    const [resolvedValues, setResolvedValues] = useState<Map<string, string>>(new Map())
    const [loading, setLoading] = useState(false)
    const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

    const currentValues = useMemo(
        () => (value === null || value === undefined ? [] : Array.isArray(value) ? value.map(String) : [String(value)]),
        [value]
    )

    const fetchGroups = useCallback(
        async (search?: string): Promise<Group[]> => {
            if (!currentTeamId) {
                return []
            }
            const params: Record<string, string | number> = { group_type_index: groupTypeIndex }
            if (search) {
                params.search = search
            }
            const response = await api.get(
                `api/environments/${currentTeamId}/groups/?${new URLSearchParams(
                    Object.entries(params).map(([k, v]) => [k, String(v)])
                ).toString()}`
            )
            return response.results ?? []
        },
        [currentTeamId, groupTypeIndex]
    )

    const updateOptionsFromGroups = useCallback(
        (groups: Group[]): void => {
            setSearchOptions(
                groups.map((g) => ({
                    key: g.group_key,
                    label: groupDisplayId(g.group_key, g.group_properties),
                }))
            )
            setResolvedValues((prev) => {
                const next = new Map(prev)
                for (const g of groups) {
                    next.set(g.group_key, groupDisplayId(g.group_key, g.group_properties))
                }
                return next
            })
        },
        [setSearchOptions, setResolvedValues]
    )

    useEffect(() => {
        if (currentValues.length === 0 || !currentTeamId) {
            return
        }

        const unresolved = currentValues.filter((v) => !resolvedValues.has(v))
        if (unresolved.length === 0) {
            return
        }

        void Promise.all(
            unresolved.map(async (groupKey) => {
                try {
                    const response = await api.get(
                        `api/environments/${currentTeamId}/groups/find?${new URLSearchParams({
                            group_type_index: String(groupTypeIndex),
                            group_key: groupKey,
                        }).toString()}`
                    )
                    return [groupKey, groupDisplayId(response.group_key, response.group_properties)] as const
                } catch {
                    return [groupKey, groupKey] as const
                }
            })
        ).then((results) => {
            setResolvedValues((prev) => {
                const next = new Map(prev)
                for (const [key, label] of results) {
                    next.set(key, label)
                }
                return next
            })
        })
    }, [currentValues, currentTeamId, groupTypeIndex]) // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        setLoading(true)
        void fetchGroups()
            .then(updateOptionsFromGroups)
            .finally(() => setLoading(false))
    }, [fetchGroups, updateOptionsFromGroups])

    const onSearchChange = useCallback(
        (input: string): void => {
            if (debounceTimer.current) {
                clearTimeout(debounceTimer.current)
            }
            debounceTimer.current = setTimeout(() => {
                setLoading(true)
                void fetchGroups(input.trim() || undefined)
                    .then(updateOptionsFromGroups)
                    .finally(() => setLoading(false))
            }, 300)
        },
        [fetchGroups, updateOptionsFromGroups]
    )

    const options = useMemo(() => {
        const optionMap = new Map<string, GroupOption>()
        for (const opt of searchOptions) {
            optionMap.set(opt.key, opt)
        }
        for (const v of currentValues) {
            if (!optionMap.has(v)) {
                optionMap.set(v, { key: v, label: resolvedValues.get(v) ?? v })
            }
        }
        return Array.from(optionMap.values())
    }, [searchOptions, currentValues, resolvedValues])

    const formattedValues = currentValues.map((v) => resolvedValues.get(v) ?? v)

    if (!editable) {
        return <>{formattedValues.join(' or ')}</>
    }

    return (
        <LemonInputSelect
            data-attr="prop-val"
            loading={loading}
            value={currentValues}
            mode={isMultiSelect ? 'multiple' : 'single'}
            singleValueAsSnack
            allowCustomValues
            onChange={(nextVal) => (isMultiSelect ? onChange(nextVal) : onChange(nextVal[0]))}
            onInputChange={onSearchChange}
            placeholder="Search groups by name..."
            size={size}
            autoFocus={autoFocus}
            disableFiltering
            options={options}
        />
    )
}
