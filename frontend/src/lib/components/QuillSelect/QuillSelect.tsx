import { Fragment } from 'react'

import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'

export type QuillSelectValue = string | number | boolean | null

export interface QuillSelectOption<T extends QuillSelectValue> {
    value: T
    /** Shown in the trigger and, unless `description` is set, alone in the list. */
    label: React.ReactNode
    /** A muted second line in the list. */
    description?: React.ReactNode
    icon?: React.ReactNode
    /** Disables the option and shows the reason beside it. */
    disabledReason?: string | null
    'data-attr'?: string
}

export interface QuillSelectGroup<T extends QuillSelectValue> {
    label?: React.ReactNode
    options: QuillSelectOption<T>[]
}

export interface QuillSelectProps<T extends QuillSelectValue> {
    value: T | null | undefined
    onChange: (value: T) => void
    /** A flat list, or groups shown with a label and separated from each other. */
    options: QuillSelectOption<T>[] | QuillSelectGroup<T>[]
    placeholder?: string
    disabled?: boolean
    disabledReason?: React.ReactNode
    fullWidth?: boolean
    defaultOpen?: boolean
    className?: string
    id?: string
    'aria-label'?: string
    'data-attr'?: string
}

function isGroupList<T extends QuillSelectValue>(
    options: QuillSelectOption<T>[] | QuillSelectGroup<T>[]
): options is QuillSelectGroup<T>[] {
    return options.length > 0 && 'options' in options[0]
}

/** A quill `Select` for a short, fixed list of values. */
export function QuillSelect<T extends QuillSelectValue>({
    value,
    onChange,
    options,
    placeholder = 'Select a value',
    disabled,
    disabledReason,
    fullWidth,
    defaultOpen,
    className,
    id,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: QuillSelectProps<T>): JSX.Element {
    const groups: QuillSelectGroup<T>[] = isGroupList(options) ? options : [{ options }]
    const allOptions = groups.flatMap((group) => group.options)
    const isDisabled = disabled || !!disabledReason

    const trigger = (
        <SelectTrigger
            id={id}
            aria-label={ariaLabel}
            data-attr={dataAttr}
            disabled={isDisabled}
            className={cn('min-w-0', fullWidth && 'w-full', className)}
        >
            <SelectValue className="min-w-0 truncate">
                {(current: T | null) => {
                    const selected = allOptions.find((option) => option.value === current)
                    return selected ? selected.label : current == null ? placeholder : String(current)
                }}
            </SelectValue>
        </SelectTrigger>
    )

    return (
        <Select
            value={value ?? null}
            onValueChange={(newValue) => {
                if (newValue !== null || allOptions.some((option) => option.value === null)) {
                    onChange(newValue as T)
                }
            }}
            disabled={isDisabled}
            defaultOpen={defaultOpen}
        >
            {disabledReason ? (
                <Tooltip>
                    <TooltipTrigger render={trigger} />
                    <TooltipContent className="max-w-80">{disabledReason}</TooltipContent>
                </Tooltip>
            ) : (
                trigger
            )}
            {/* The block class keeps a Lemon popover that hosts this select open while an option is picked. */}
            <SelectContent alignItemWithTrigger={false} align="start" className={CLICK_OUTSIDE_BLOCK_CLASS}>
                {groups.map((group, groupIndex) => (
                    <Fragment key={groupIndex}>
                        {groupIndex > 0 ? <SelectSeparator /> : null}
                        <SelectGroup>
                            {group.label ? <SelectGroupLabel>{group.label}</SelectGroupLabel> : null}
                            {group.options.map((option) => (
                                <SelectItem
                                    key={String(option.value)}
                                    value={option.value}
                                    disabled={!!option.disabledReason}
                                    data-attr={option['data-attr']}
                                >
                                    {option.icon}
                                    <span className="flex min-w-0 flex-1 flex-col">
                                        <span>{option.label}</span>
                                        {option.description ? (
                                            <Text size="xs" variant="muted" render={<span />}>
                                                {option.description}
                                            </Text>
                                        ) : null}
                                    </span>
                                    {option.disabledReason ? (
                                        <Text size="xs" variant="muted" render={<span />}>
                                            {option.disabledReason}
                                        </Text>
                                    ) : null}
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </Fragment>
                ))}
            </SelectContent>
        </Select>
    )
}
