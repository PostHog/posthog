import type { ReactElement } from 'react'

import { cn } from '../utils'

export interface SelectOption<T extends string = string> {
    value: T
    label: string
}

export interface SelectProps<T extends string = string> {
    value: T
    onChange: (value: T) => void
    options: SelectOption<T>[]
    size?: 'sm' | 'md'
    className?: string
}

const sizeStyles = {
    sm: 'px-2 py-1 text-xs',
    md: 'px-3 py-1.5 text-sm',
} as const

export function Select<T extends string = string>({
    value,
    onChange,
    options,
    size = 'sm',
    className,
}: SelectProps<T>): ReactElement {
    return (
        <select
            value={value}
            onChange={(e) => onChange(e.target.value as T)}
            className={cn(
                'rounded-md border border-border-primary bg-bg-primary text-text-primary',
                'cursor-pointer outline-none transition-colors',
                'hover:bg-bg-secondary focus:border-info',
                sizeStyles[size],
                className
            )}
        >
            {options.map((option) => (
                <option key={option.value} value={option.value}>
                    {option.label}
                </option>
            ))}
        </select>
    )
}
