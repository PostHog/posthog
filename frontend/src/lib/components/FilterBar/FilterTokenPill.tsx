import { forwardRef, ReactNode } from 'react'

import { FilterPickerTokenPill } from '../FilterPicker'
import { FilterPickerTokenPart } from '../FilterPicker/FilterPicker.types'

export const FilterTokenPill = forwardRef<
    HTMLDivElement,
    {
        parts?: ReactNode[]
        label?: ReactNode
        title?: string
        onRemove?: () => void
        onClick?: () => void
        className?: string
    }
>(function FilterTokenPill({ parts, label, title, onRemove, onClick, className }, ref): JSX.Element {
    const tokenParts: FilterPickerTokenPart[] = parts?.length
        ? parts.map((part, index) => ({ key: String(index), kind: 'text', label: part }))
        : [{ key: 'label', kind: 'text', label }]

    return (
        <FilterPickerTokenPill
            ref={ref}
            token={{
                id: title ?? 'filter-token',
                parts: tokenParts,
                title,
                removable: !!onRemove,
                editable: !!onClick,
            }}
            onEdit={onClick}
            onRemove={onRemove}
            className={className}
        />
    )
})
