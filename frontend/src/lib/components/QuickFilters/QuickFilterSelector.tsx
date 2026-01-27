import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { QuickFilterOption } from '~/types'

interface QuickFilterSelectorProps {
    label: string
    options: QuickFilterOption[]
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

export function QuickFilterSelector({
    label,
    options,
    selectedOptionId,
    onChange,
}: QuickFilterSelectorProps): JSX.Element {
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
