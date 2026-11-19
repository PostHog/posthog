import { Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { ALL_VALUE } from './variables'

interface DashboardV2SelectVariableProps {
    name: string
    label: string
    options: string[]
    includeAll: boolean
    value: string | undefined
    onChange: (value: string) => void
}

export function DashboardV2SelectVariable({
    name,
    label,
    options,
    includeAll,
    value,
    onChange,
}: DashboardV2SelectVariableProps): JSX.Element {
    const id = `dashboard-v2-variable-${name}`
    const items = [
        ...(includeAll ? [{ value: ALL_VALUE, label: 'All' }] : []),
        ...options.map((option) => ({ value: option, label: option })),
    ]

    return (
        <div className="flex items-center gap-1">
            <Label htmlFor={id}>{label}</Label>
            <Select items={items} value={value ?? null} onValueChange={(next) => next !== null && onChange(next)}>
                <SelectTrigger id={id} size="sm" data-attr="dashboard-v2-variable-select">
                    <SelectValue placeholder="Choose" />
                </SelectTrigger>
                <SelectContent>
                    {items.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                            {item.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
