import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Field, FieldLabel } from '@posthog/quill'

export interface FilterOption {
    value: string
    label: string
}

/** A labeled single choice. The first option is the "no filter" choice and has the value `all`. */
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
        <Field className="w-auto min-w-0">
            <FieldLabel>{label}</FieldLabel>
            <Select
                items={options}
                value={value}
                onValueChange={(next) => {
                    if (typeof next === 'string' && next !== value) {
                        onChange(next)
                    }
                }}
            >
                <SelectTrigger className="w-44 max-w-full" data-attr={dataAttr}>
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
        </Field>
    )
}
