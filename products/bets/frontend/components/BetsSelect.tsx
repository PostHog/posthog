import type { ComponentProps } from 'react'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

export function BetsSelect({
    value,
    items,
    onChange,
    disabled,
    trigger,
}: {
    value: string
    items: { value: string; label: string }[]
    onChange: (value: string | null) => void
    disabled?: boolean
    trigger: ComponentProps<typeof SelectTrigger>
}): JSX.Element {
    return (
        <Select value={value} items={items} disabled={disabled} onValueChange={onChange}>
            <SelectTrigger {...trigger}>
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {items.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                        {item.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
