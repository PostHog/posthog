import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

export interface QuillLevelSelectOption<T extends string> {
    value: T
    label: string
    /** Keeps the option visible but unselectable, with the reason in a tooltip. */
    disabledReason?: string
}

interface QuillLevelSelectProps<T extends string> {
    value: T | null
    options: QuillLevelSelectOption<T>[]
    onChange: (value: T | null) => void
    /** Offers "No override" (a null value) in its own group above the options. */
    allowNoOverride?: boolean
    placeholder?: string
    disabledReason?: string
    /** Explains the current value on hover. A disabled select shows its disabledReason instead. */
    tooltip?: string
    /** Trigger content for the chosen value, when it should read differently from the option label. */
    renderValue?: (value: T) => React.ReactNode
    className?: string
    'data-attr'?: string
}

type SelectEntry<T extends string> = { value: T | null; label: string }

const NO_OVERRIDE_LABEL = 'No override'

/** An access level select, where an option can be unavailable for a stated reason. */
export function QuillLevelSelect<T extends string>({
    value,
    options,
    onChange,
    allowNoOverride,
    placeholder = 'Select level…',
    disabledReason,
    tooltip,
    renderValue,
    className,
    'data-attr': dataAttr,
}: QuillLevelSelectProps<T>): JSX.Element {
    const items: SelectEntry<T>[] = [
        ...(allowNoOverride ? [{ value: null, label: NO_OVERRIDE_LABEL }] : []),
        ...options.map((option) => ({ value: option.value, label: option.label })),
    ]

    const valueContent = (
        <SelectValue>
            {(selected: T | null) =>
                selected === null ? (
                    allowNoOverride ? (
                        NO_OVERRIDE_LABEL
                    ) : (
                        <span className="text-muted-foreground">{placeholder}</span>
                    )
                ) : renderValue ? (
                    renderValue(selected)
                ) : (
                    (options.find((option) => option.value === selected)?.label ?? selected)
                )
            }
        </SelectValue>
    )

    return (
        <Select<T | null> items={items} value={value} onValueChange={(next) => onChange(next as T | null)}>
            {tooltip && !disabledReason ? (
                <Tooltip>
                    <TooltipTrigger delay={0} render={<SelectTrigger className={className} data-attr={dataAttr} />}>
                        {valueContent}
                    </TooltipTrigger>
                    <TooltipContent>{tooltip}</TooltipContent>
                </Tooltip>
            ) : (
                <SelectTrigger className={className} disabledReason={disabledReason} data-attr={dataAttr}>
                    {valueContent}
                </SelectTrigger>
            )}
            <SelectContent>
                {allowNoOverride && (
                    <>
                        <SelectGroup>
                            <SelectItem value={null}>{NO_OVERRIDE_LABEL}</SelectItem>
                        </SelectGroup>
                        <SelectSeparator />
                    </>
                )}
                <SelectGroup>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value} disabledReason={option.disabledReason}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
