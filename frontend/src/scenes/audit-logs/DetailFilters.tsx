import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconInfo, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSearchableSelect,
    LemonSelect,
    Tooltip,
} from '@posthog/lemon-ui'

import { midEllipsis } from 'lib/utils'

import { ActiveDetailFilter, advancedActivityLogsLogic } from './advancedActivityLogsLogic'

interface DetailFilterRowProps {
    filter: ActiveDetailFilter
}

const DetailFilterRow = ({ filter }: DetailFilterRowProps): JSX.Element => {
    const { availableFilters, activeFilters } = useValues(advancedActivityLogsLogic)
    const { updateActiveFilter, removeActiveFilter } = useActions(advancedActivityLogsLogic)

    const [localValue, setLocalValue] = useState<string | string[]>(filter.value)
    const [localFieldPath, setLocalFieldPath] = useState<string>(filter.fieldPath)
    const [fieldPathError, setFieldPathError] = useState<string | null>(null)
    const debounceTimerRef = useRef<NodeJS.Timeout | null>(null)

    const fieldOptionsForRow = useMemo(() => {
        if (!availableFilters?.detail_fields) {
            return []
        }

        const selectedFields = new Set(
            activeFilters.filter((f) => f.key !== filter.key && !f.isCustom).map((f) => f.fieldPath)
        )

        // Group by field name instead of scope
        const fieldGroups = new Map<string, { scopes: string[]; fullPaths: string[] }>()

        Object.entries(availableFilters.detail_fields).forEach(([scope, scopeData]) => {
            scopeData.fields.forEach((field) => {
                const fieldValue = `${scope}::${field.name}`

                if (!selectedFields.has(fieldValue) || fieldValue === filter.fieldPath) {
                    if (!fieldGroups.has(field.name)) {
                        fieldGroups.set(field.name, { scopes: [], fullPaths: [] })
                    }

                    const group = fieldGroups.get(field.name)!
                    if (!group.scopes.includes(scope)) {
                        group.scopes.push(scope)
                        group.fullPaths.push(fieldValue)
                    }
                }
            })
        })

        // Convert to options with composite display
        const fieldOptions = Array.from(fieldGroups.entries())
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([fieldName, group]) => {
                // Get the last part of the field path after splitting by "."
                const displayName = fieldName.split('.').pop() || fieldName

                // Create tooltip with full path and scopes
                const scopeNames = group.scopes.map((scope) => scope.replace(/([A-Z])/g, ' $1').trim()).join(', ')
                const displayPath = fieldName.length > 50 ? midEllipsis(fieldName, 50) : fieldName

                // For single scope, use direct field path; for multiple, use first one as primary
                const primaryValue = group.fullPaths[0]

                return {
                    value: primaryValue,
                    label: (
                        <div className="flex flex-col">
                            <div>{displayName}</div>
                            <div className="text-xs text-muted">{displayPath}</div>
                        </div>
                    ),
                    tooltip: (
                        <div className="text-xs">
                            <div>
                                <strong>Full path:</strong>
                                <br />
                                {fieldName}
                            </div>
                            <br />
                            <div>
                                <strong>Available in:</strong>
                                <br />
                                {scopeNames}
                            </div>
                        </div>
                    ),
                }
            })

        return [
            {
                title: 'Available Fields',
                options: fieldOptions,
            },
        ]
    }, [availableFilters, filter.key, filter.fieldPath, activeFilters])

    const validateCustomFieldPath = (path: string): string | null => {
        if (!path || !path.trim()) {
            return 'Field path cannot be empty'
        }
        const cleanPath = path.trim()
        const validPattern = /^[a-zA-Z0-9_.[\]]+$/
        if (!validPattern.test(cleanPath)) {
            return 'Field path can only contain letters, numbers, dots, underscores, and square brackets'
        }
        return null
    }

    useEffect(() => {
        setLocalValue(filter.value)
    }, [filter.value])

    useEffect(() => {
        setLocalFieldPath(filter.fieldPath)
    }, [filter.fieldPath])

    const handleOperationChange = (operation: ActiveDetailFilter['operation']): void => {
        let newValue = filter.value
        if (operation === 'in' && !Array.isArray(filter.value)) {
            newValue = filter.value && (filter.value as string).trim() ? [filter.value as string] : []
        }
        setLocalValue(newValue)
        updateActiveFilter(filter.key, { operation, value: newValue })
    }

    const handleValueChange = (value: string | string[]): void => {
        setLocalValue(value)

        if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current)
        }

        const hasContent = Array.isArray(value) ? value.some((v) => v.length > 0) : value.length > 0

        if (hasContent) {
            debounceTimerRef.current = setTimeout(() => {
                updateActiveFilter(filter.key, { value })
            }, 500)
        }
    }

    const handleFieldChange = (newFieldPath: string): void => {
        if (newFieldPath !== filter.fieldPath) {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current)
            }
            updateActiveFilter(filter.key, { fieldPath: newFieldPath })
        }
    }

    const handleCustomFieldPathChange = (newPath: string): void => {
        setLocalFieldPath(newPath)
        const error = validateCustomFieldPath(newPath)
        setFieldPathError(error)

        if (!error && newPath && newPath !== filter.fieldPath) {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current)
            }
            debounceTimerRef.current = setTimeout(() => {
                const cleanPath = newPath.trim()
                if (cleanPath && cleanPath !== filter.fieldPath) {
                    updateActiveFilter(filter.key, { fieldPath: cleanPath })
                }
            }, 500)
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
            {filter.isCustom ? (
                <div className="min-w-60">
                    <LemonInput
                        value={localFieldPath}
                        onChange={handleCustomFieldPathChange}
                        placeholder="Enter custom field path"
                        status={fieldPathError ? 'danger' : undefined}
                        size="small"
                    />
                    {fieldPathError && <div className="text-xs text-danger mt-1">{fieldPathError}</div>}
                </div>
            ) : (
                <LemonSelect
                    value={filter.fieldPath}
                    onChange={handleFieldChange}
                    options={fieldOptionsForRow}
                    placeholder="Select field"
                    size="small"
                    className="min-w-60"
                />
            )}

            <LemonSelect
                value={filter.operation}
                onChange={handleOperationChange}
                options={[
                    { value: 'exact', label: 'equals' },
                    { value: 'contains', label: 'contains' },
                    { value: 'in', label: 'is one of' },
                ]}
                size="small"
                className="min-w-32"
            />

            {filter.operation === 'in' ? (
                <LemonInputSelect
                    mode="multiple"
                    value={localValue as string[]}
                    onChange={handleValueChange}
                    allowCustomValues
                    placeholder="Enter values"
                    size="small"
                    className="min-w-60"
                />
            ) : (
                <LemonInput
                    value={localValue as string}
                    onChange={handleValueChange}
                    placeholder="Enter value"
                    size="small"
                    className="min-w-60"
                />
            )}

            <LemonButton
                icon={<IconTrash />}
                size="small"
                type="tertiary"
                onClick={() => removeActiveFilter(filter.key)}
                tooltip="Remove filter"
            />
        </div>
    )
}

export const DetailFilters = (): JSX.Element => {
    const { activeFilters, availableFilters } = useValues(advancedActivityLogsLogic)
    const { addActiveFilter } = useActions(advancedActivityLogsLogic)

    const fieldOptions = useMemo(() => {
        if (!availableFilters?.detail_fields) {
            return []
        }

        const selectedFields = new Set(activeFilters.filter((f) => !f.isCustom).map((f) => f.fieldPath))

        // Group by field name instead of scope
        const fieldGroups = new Map<string, { scopes: string[]; fullPaths: string[] }>()

        Object.entries(availableFilters.detail_fields).forEach(([scope, scopeData]) => {
            scopeData.fields.forEach((field) => {
                const fieldValue = `${scope}::${field.name}`

                if (!selectedFields.has(fieldValue)) {
                    if (!fieldGroups.has(field.name)) {
                        fieldGroups.set(field.name, { scopes: [], fullPaths: [] })
                    }

                    const group = fieldGroups.get(field.name)!
                    if (!group.scopes.includes(scope)) {
                        group.scopes.push(scope)
                        group.fullPaths.push(fieldValue)
                    }
                }
            })
        })

        // Convert to options with composite display
        const fieldOptions = Array.from(fieldGroups.entries())
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([fieldName, group]) => {
                // Get the last part of the field path after splitting by "."
                const displayName = fieldName.split('.').pop() || fieldName

                // Create tooltip with full path and scopes
                const scopeNames = group.scopes.map((scope) => scope.replace(/([A-Z])/g, ' $1').trim()).join(', ')
                const displayPath = fieldName.length > 50 ? midEllipsis(fieldName, 50) : fieldName

                // For single scope, use direct field path; for multiple, use first one as primary
                const primaryValue = group.fullPaths[0]

                return {
                    value: primaryValue,
                    label: (
                        <div className="flex flex-col">
                            <div>{displayName}</div>
                            <div className="text-xs text-muted">{displayPath}</div>
                        </div>
                    ),
                    tooltip: (
                        <div className="text-xs">
                            <div>
                                <strong>Full path:</strong>
                                <br />
                                {fieldName}
                            </div>
                            <br />
                            <div>
                                <strong>Available in:</strong>
                                <br />
                                {scopeNames}
                            </div>
                        </div>
                    ),
                }
            })

        const sections = [
            {
                title: 'Available Fields',
                options: fieldOptions,
            },
        ]

        sections.push({
            title: 'Custom',
            options: [
                {
                    value: '__add_custom__',
                    label: <span>Custom field path...</span>,
                    tooltip: <div>Enter a custom field path manually</div>,
                },
            ],
        })

        return sections
    }, [availableFilters, activeFilters])

    if (!availableFilters?.detail_fields || Object.keys(availableFilters.detail_fields).length === 0) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
                <label className="block text-sm font-medium">Detail filters</label>
                <Tooltip title="Filter by specific fields within the activity log details field. For example, filter by changes to specific dashboard properties, feature flag variations, or other detailed attributes logged with each activity.">
                    <IconInfo className="w-4 h-4 text-muted-alt cursor-help" />
                </Tooltip>
            </div>

            <div className="flex flex-col gap-2">
                {activeFilters.map((filter) => (
                    <DetailFilterRow key={filter.key} filter={filter} />
                ))}
            </div>

            <LemonSearchableSelect
                value={undefined}
                onChange={(value) => {
                    if (value === '__add_custom__') {
                        addActiveFilter('', true)
                    } else if (value) {
                        addActiveFilter(value, false)
                    }
                }}
                options={fieldOptions}
                placeholder="Add filter"
                searchPlaceholder="Search fields..."
                searchKeys={['value']}
                icon={<IconPlus />}
                size="small"
                className="w-[200px]"
            />
        </div>
    )
}
