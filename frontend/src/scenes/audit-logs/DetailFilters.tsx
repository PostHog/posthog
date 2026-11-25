import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconInfo, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect, LemonSelect, LemonSelectSection, Tooltip } from '@posthog/lemon-ui'

import { ActiveDetailFilter, advancedActivityLogsLogic } from './advancedActivityLogsLogic'
import { DetailFieldSelect } from './DetailFieldSelect'

const CUSTOM_FIELD_VALUE = '__add_custom__'

const CUSTOM_FIELD_SECTIONS: LemonSelectSection<string>[] = [
    {
        title: 'Custom',
        options: [
            {
                value: CUSTOM_FIELD_VALUE,
                label: <span>Custom field path...</span>,
                tooltip: <div>Enter a custom field path manually</div>,
            },
        ],
    },
]

interface DetailFilterRowProps {
    filter: ActiveDetailFilter
}

const DetailFilterRow = ({ filter }: DetailFilterRowProps): JSX.Element => {
    const { detailFieldChoices, activeFilters } = useValues(advancedActivityLogsLogic)
    const { updateActiveFilter, removeActiveFilter } = useActions(advancedActivityLogsLogic)

    const [localValue, setLocalValue] = useState<string | string[]>(filter.value)
    const [localFieldPath, setLocalFieldPath] = useState<string>(filter.fieldPath)
    const [fieldPathError, setFieldPathError] = useState<string | null>(null)
    const debounceTimerRef = useRef<NodeJS.Timeout | null>(null)

    const otherFieldPaths = useMemo(
        () => activeFilters.filter((f) => f.key !== filter.key && !f.isCustom).map((f) => f.fieldPath),
        [activeFilters, filter.key]
    )

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
                <DetailFieldSelect
                    choices={detailFieldChoices}
                    excludedFieldPaths={otherFieldPaths}
                    value={filter.fieldPath}
                    onChange={handleFieldChange}
                    placeholder="Select field"
                    className="min-w-60"
                    data-attr="audit-logs-detail-filter-field"
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
    const { activeFilters, availableFilters, detailFieldChoices } = useValues(advancedActivityLogsLogic)
    const { addActiveFilter } = useActions(advancedActivityLogsLogic)

    const selectedFieldPaths = useMemo(
        () => activeFilters.filter((f) => !f.isCustom).map((f) => f.fieldPath),
        [activeFilters]
    )

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

            <DetailFieldSelect
                choices={detailFieldChoices}
                excludedFieldPaths={selectedFieldPaths}
                onChange={(value) =>
                    addActiveFilter(value === CUSTOM_FIELD_VALUE ? '' : value, value === CUSTOM_FIELD_VALUE)
                }
                placeholder="Add filter"
                icon={<IconPlus />}
                extraSections={CUSTOM_FIELD_SECTIONS}
                className="w-[200px]"
                data-attr="audit-logs-detail-filter-add"
            />
        </div>
    )
}
