import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { QuickFilterOption } from '~/types'

interface QuickFilterSelectorProps {
    label: string
    options: QuickFilterOption[]
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

function truncateLabel(label: string, maxLength: number): string {
    if (label.length <= maxLength) {
        return label
    }

    const charsToShow = Math.floor((maxLength - 3) / 2)
    return `${label.slice(0, charsToShow)}...${label.slice(-charsToShow)}`
}

export function QuickFilterSelector({
    label,
    options,
    selectedOptionId,
    onChange,
}: QuickFilterSelectorProps): JSX.Element {
    const maxLength = 30
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

    const selectedOption = useMemo(() => {
        if (selectedOptionId === null) {
            return null
        }
        return options.find((opt) => opt.id === selectedOptionId)
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
            renderButtonContent={(leaf) => {
                if (!leaf || !leaf.value || !selectedOption) {
                    return label
                }
                return (
                    <span title={selectedOption.label.length > maxLength ? selectedOption.label : undefined}>
                        {truncateLabel(selectedOption.label, maxLength)}
                    </span>
                )
            }}
        />
    )
}
