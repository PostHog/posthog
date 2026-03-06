import type { ReactElement, ReactNode } from 'react'

import { cn } from '../utils'

export interface DescriptionListItem {
    label: string
    value: ReactNode
}

export interface DescriptionListProps {
    items: DescriptionListItem[]
    columns?: 1 | 2
    className?: string
}

export function DescriptionList({ items, columns = 1, className }: DescriptionListProps): ReactElement {
    const filtered = items.filter((item) => item.value != null && item.value !== '')
    if (filtered.length === 0) {
        return <></>
    }

    return (
        <dl
            className={cn(
                'grid gap-x-4 gap-y-2 text-sm',
                columns === 2 ? 'grid-cols-[auto_1fr_auto_1fr]' : 'grid-cols-[auto_1fr]',
                className
            )}
        >
            {filtered.map((item) => (
                <div key={item.label} className="contents">
                    <dt className="text-text-secondary font-medium whitespace-nowrap">{item.label}</dt>
                    <dd className="text-text-primary">{item.value}</dd>
                </div>
            ))}
        </dl>
    )
}
