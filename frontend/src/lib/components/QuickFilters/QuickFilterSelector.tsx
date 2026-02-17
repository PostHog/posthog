import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'

import { PropertyOperator, QuickFilter, QuickFilterOption } from '~/types'

import { isAutoDiscoveryQuickFilter } from './utils'

interface QuickFilterSelectorProps {
    filter: QuickFilter
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

export function QuickFilterSelector({ filter, selectedOptionId, onChange }: QuickFilterSelectorProps): JSX.Element {
    if (isAutoDiscoveryQuickFilter(filter)) {
        return (
            <AutoDiscoveryQuickFilterSelector filter={filter} selectedOptionId={selectedOptionId} onChange={onChange} />
        )
    }

    const options = filter.options as QuickFilterOption[]
    return (
        <ManualQuickFilterSelector
            label={filter.name}
            options={options}
            selectedOptionId={selectedOptionId}
            onChange={onChange}
        />
    )
}

function ManualQuickFilterSelector({
    label,
    options,
    selectedOptionId,
    onChange,
}: {
    label: string
    options: QuickFilterOption[]
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}): JSX.Element {
    const allOptions = useMemo(
        () => [
            { value: null, label: `Any ${label.toLowerCase()}` },
            ...options.map((opt) => ({
                value: opt.id,
                label: opt.label,
            })),
        ],
        [options, label]
    )

    const displayValue = useMemo(() => {
        if (selectedOptionId === null) {
            return null
        }
        return options.some((opt) => opt.id === selectedOptionId) ? selectedOptionId : null
    }, [selectedOptionId, options])

    return (
        <LemonSelect
            value={displayValue}
            onChange={(selectedId) => {
                if (selectedId === null) {
                    onChange(null)
                } else {
                    const selected = options.find((opt) => opt.id === selectedId)
                    onChange(selected || null)
                }
            }}
            options={allOptions}
            size="small"
            placeholder={label}
            dropdownMatchSelectWidth={false}
        />
    )
}

interface PropValue {
    name?: string | boolean
}

function AutoDiscoveryQuickFilterSelector({
    filter,
    selectedOptionId,
    onChange,
}: {
    filter: QuickFilter & { options: { value_pattern: string; operator: PropertyOperator } }
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}): JSX.Element {
    const config = filter.options
    const [values, setValues] = useState<PropValue[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const [searchTerm, setSearchTerm] = useState('')
    const abortControllerRef = useRef<AbortController | null>(null)
    const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const fetchValues = useCallback(
        async (search: string) => {
            abortControllerRef.current?.abort()
            const controller = new AbortController()
            abortControllerRef.current = controller

            setIsLoading(true)
            try {
                let url = `api/event/values/?key=${encodeURIComponent(filter.property_name)}`
                if (search) {
                    url += `&value=${encodeURIComponent(search)}`
                }
                const results: PropValue[] = await api.get(url, { signal: controller.signal })
                if (!controller.signal.aborted) {
                    setValues(results)
                }
            } catch (e: any) {
                if (e.name !== 'AbortError') {
                    setValues([])
                }
            } finally {
                if (!controller.signal.aborted) {
                    setIsLoading(false)
                }
            }
        },
        [filter.property_name]
    )

    const debouncedFetch = useCallback(
        (search: string) => {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current)
            }
            debounceTimerRef.current = setTimeout(() => fetchValues(search), 300)
        },
        [fetchValues]
    )

    useEffect(() => {
        return () => {
            abortControllerRef.current?.abort()
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current)
            }
        }
    }, [])

    const handleVisibilityChange = useCallback(
        (visible: boolean) => {
            if (visible) {
                fetchValues(searchTerm)
            } else {
                setSearchTerm('')
            }
        },
        [fetchValues, searchTerm]
    )

    const handleSearchChange = useCallback(
        (value: string) => {
            setSearchTerm(value)
            debouncedFetch(value)
        },
        [debouncedFetch]
    )

    const filteredValues = useMemo(() => {
        if (!config.value_pattern) {
            return values
        }
        try {
            const regex = new RegExp(config.value_pattern)
            return values.filter((pv) => regex.test(String(pv.name ?? '')))
        } catch {
            return values
        }
    }, [values, config.value_pattern])

    const dynamicOptions: QuickFilterOption[] = useMemo(
        () =>
            filteredValues.map((pv) => ({
                id: String(pv.name ?? ''),
                value: String(pv.name ?? ''),
                label: String(pv.name ?? ''),
                operator: config.operator || PropertyOperator.Exact,
            })),
        [filteredValues, config.operator]
    )

    const allOptions = useMemo(
        () => [
            {
                label: () => (
                    <LemonInput
                        type="search"
                        placeholder="Search values..."
                        autoFocus
                        value={searchTerm}
                        onChange={handleSearchChange}
                        fullWidth
                        onClick={(e) => e.stopPropagation()}
                        className="mb-1"
                    />
                ),
                custom: true,
            } as any,
            { value: null, label: `Any ${filter.name.toLowerCase()}` },
            ...dynamicOptions.map((opt) => ({
                value: opt.id,
                label: <span className="truncate max-w-200">{opt.label}</span>,
            })),
        ],
        [dynamicOptions, filter.name, searchTerm, handleSearchChange]
    )

    const displayValue = useMemo(() => {
        if (selectedOptionId === null) {
            return null
        }
        return dynamicOptions.some((opt) => opt.id === selectedOptionId) ? selectedOptionId : null
    }, [selectedOptionId, dynamicOptions])

    return (
        <LemonSelect
            value={displayValue}
            onChange={(selectedId) => {
                if (selectedId === null) {
                    onChange(null)
                } else {
                    const selected = dynamicOptions.find((opt) => opt.id === selectedId)
                    onChange(selected || null)
                }
                setSearchTerm('')
            }}
            options={allOptions}
            size="small"
            placeholder={filter.name}
            dropdownMatchSelectWidth={false}
            loading={isLoading}
            onVisibilityChange={handleVisibilityChange}
            allowClear
        />
    )
}
