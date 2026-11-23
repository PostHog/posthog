import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

export interface FilterOption {
    value: string
    label: string
}

/** A compact single choice with its name inside the control: "Status: All". The first option is the "no filter" choice. */
export function WarehouseFilterSelect({
    label,
    value,
    options,
    onChange,
    'data-attr': dataAttr,
}: {
    label: string
    value: string
    options: FilterOption[]
    onChange: (value: string) => void
    'data-attr': string
}): JSX.Element {
    return (
        <Select
            items={options}
            value={value}
            onValueChange={(next) => {
                if (typeof next === 'string' && next !== value) {
                    onChange(next)
                }
            }}
        >
            <SelectTrigger size="sm" className="max-w-48" aria-label={label} data-attr={dataAttr}>
                <span className="text-muted-foreground">{label}:</span>
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
