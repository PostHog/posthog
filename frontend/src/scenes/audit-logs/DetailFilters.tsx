import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect, LemonSearchableSelect, LemonSelect } from '@posthog/lemon-ui'

import { DetailFilter, advancedActivityLogsLogic } from './advancedActivityLogsLogic'

interface DetailFilterRowProps {
    fieldPath: string
    filter: DetailFilter
    availableFields: Array<{ value: string; label: string }>
    onUpdate: (fieldPath: string, filter: DetailFilter | null) => void
    onRemove: () => void
}

const DetailFilterRow = ({
    fieldPath,
    filter,
    availableFields,
    onUpdate,
    onRemove,
}: DetailFilterRowProps): JSX.Element => {
    const [localValue, setLocalValue] = useState<string | string[]>(filter.value)
    const debounceTimerRef = useRef<NodeJS.Timeout | null>(null)

    useEffect(() => {
        setLocalValue(filter.value)
    }, [filter.value])

    const handleOperationChange = (operation: DetailFilter['operation']): void => {
        const newValue = operation === 'in' && !Array.isArray(filter.value) ? [filter.value as string] : filter.value
        setLocalValue(newValue)
        onUpdate(fieldPath, { ...filter, operation, value: newValue })
    }

    const handleValueChange = (value: string | string[]): void => {
        setLocalValue(value)

        if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current)
        }

        const hasContent = Array.isArray(value) ? value.some((v) => v.length > 0) : value.length > 0

        if (hasContent) {
            debounceTimerRef.current = setTimeout(() => {
                onUpdate(fieldPath, { ...filter, value })
            }, 500)
        }
    }

    const handleFieldChange = (newFieldPath: string): void => {
        if (newFieldPath !== fieldPath) {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current)
            }
            onUpdate(fieldPath, null)
            onUpdate(newFieldPath, filter)
        }
    }

    useEffect(() => {
        return () => {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current)
            }
        }
    }, [])

    return (
        <div className="flex gap-2 items-center">
            <LemonSelect
                value={fieldPath}
                onChange={handleFieldChange}
                options={availableFields}
                placeholder="Select field"
                className="min-w-60"
            />

            <LemonSelect
                value={filter.operation}
                onChange={handleOperationChange}
                options={[
                    { value: 'exact', label: 'equals' },
                    { value: 'contains', label: 'contains' },
                    { value: 'in', label: 'is one of' },
                ]}
                className="min-w-32"
            />

            {filter.operation === 'in' ? (
                <LemonInputSelect
                    mode="multiple"
                    value={localValue as string[]}
                    onChange={handleValueChange}
                    allowCustomValues
                    placeholder="Enter values"
                    className="min-w-60"
                />
            ) : (
                <LemonInput
                    value={localValue as string}
                    onChange={handleValueChange}
                    placeholder="Enter value"
                    className="min-w-60"
                />
            )}

            <LemonButton icon={<IconTrash />} size="small" type="tertiary" onClick={onRemove} tooltip="Remove filter" />
        </div>
    )
}

export const DetailFilters = (): JSX.Element => {
    const { filters, availableFilters } = useValues(advancedActivityLogsLogic)
    const { setFilters } = useActions(advancedActivityLogsLogic)

    const detailFilters = filters.detail_filters || {}

    const buildFieldOptions = (): Array<{ title: string; options: Array<{ value: string; label: string }> }> => {
        const sections = new Map<string, Set<string>>()
        const generalFields = new Set<string>()

        if (availableFilters?.detail_fields) {
            Object.entries(availableFilters.detail_fields).forEach(([scope, scopeData]) => {
                const cleanScope = scope.replace(/([A-Z])/g, ' $1').trim() || 'General'

                if (!sections.has(cleanScope)) {
                    sections.set(cleanScope, new Set())
                }

                scopeData.fields.forEach((field) => {
                    sections.get(cleanScope)!.add(field.name)
                    if (cleanScope === 'General') {
                        generalFields.add(field.name)
                    }
                })
            })
        }

        return Array.from(sections.entries())
            .sort(([a], [b]) => (a === 'General' ? -1 : b === 'General' ? 1 : a.localeCompare(b)))
            .map(([title, fieldSet]) => {
                const fields = Array.from(fieldSet)
                    .filter((field) => title === 'General' || !generalFields.has(field))
                    .sort()
                    .map((field) => ({ value: field, label: field }))

                return { title, options: fields }
            })
            .filter((section) => section.options.length > 0)
    }

    const fieldSections = buildFieldOptions()
    const allFields = fieldSections.flatMap((section) => section.options)

    const handleAddFilter = (fieldName: string | null): void => {
        if (!fieldName) {
            return
        }
        setFilters({
            detail_filters: {
                ...detailFilters,
                [fieldName]: { operation: 'exact' as const, value: '' },
            },
        })
    }

    const handleUpdateFilter = (fieldPath: string, filter: DetailFilter | null): void => {
        const newFilters = { ...detailFilters }
        if (filter === null) {
            delete newFilters[fieldPath]
        } else {
            newFilters[fieldPath] = filter
        }
        setFilters({ detail_filters: newFilters })
    }

    const handleRemoveFilter = (fieldPath: string): void => {
        const newFilters = { ...detailFilters }
        delete newFilters[fieldPath]
        setFilters({ detail_filters: newFilters })
    }

    if (!availableFilters?.detail_fields || Object.keys(availableFilters.detail_fields).length === 0) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-2">
            <label className="block text-sm font-medium">Detail Filters</label>

            <div className="flex flex-col gap-2">
                {Object.entries(detailFilters).map(([fieldPath, filter]) => (
                    <DetailFilterRow
                        key={fieldPath}
                        fieldPath={fieldPath}
                        filter={filter}
                        availableFields={allFields}
                        onUpdate={handleUpdateFilter}
                        onRemove={() => handleRemoveFilter(fieldPath)}
                    />
                ))}
            </div>

            <LemonSearchableSelect
                value={null}
                onChange={handleAddFilter}
                options={fieldSections}
                placeholder="Add detail filter"
                searchPlaceholder="Search fields..."
                icon={<IconPlus />}
                className="w-1/4 min-w-100"
            />
        </div>
    )
}
