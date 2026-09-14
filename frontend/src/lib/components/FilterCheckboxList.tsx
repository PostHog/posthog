import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

export type FilterCheckboxOption<T extends string> = { key: T; label: string }

export interface FilterCheckboxListProps<T extends string> {
    options: readonly FilterCheckboxOption<T>[]
    value: T[]
    onChange: (value: T[]) => void
}

export function FilterCheckboxList<T extends string>({
    options,
    value,
    onChange,
}: FilterCheckboxListProps<T>): JSX.Element {
    return (
        <div className="flex flex-col gap-px">
            {options.map((option) => {
                const checked = value.includes(option.key)
                return (
                    <LemonButton
                        key={option.key}
                        type="tertiary"
                        size="small"
                        fullWidth
                        icon={<LemonCheckbox checked={checked} className="pointer-events-none" decorative />}
                        onClick={() =>
                            onChange(checked ? value.filter((item) => item !== option.key) : [...value, option.key])
                        }
                    >
                        {option.label}
                    </LemonButton>
                )
            })}
        </div>
    )
}
