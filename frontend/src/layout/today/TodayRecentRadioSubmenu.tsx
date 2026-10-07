import { DropdownMenuRadioGroup, DropdownMenuRadioItem, ItemRadio, cn } from '@posthog/quill'

import { TodayRecentFilterSubmenu } from './TodayRecentFilterSubmenu'
import { useTodaySheetMenu } from './todaySheetMenuContext'

interface TodayRecentRadioSubmenuProps<T extends string> {
    label: string
    options: { value: T; label: string; dotClassName?: string }[]
    value: T
    defaultValue: T
    onChange: (value: T) => void
    dataAttr: string
}

export function TodayRecentRadioSubmenu<T extends string>({
    label,
    options,
    value,
    defaultValue,
    onChange,
    dataAttr,
}: TodayRecentRadioSubmenuProps<T>): JSX.Element {
    const sheet = useTodaySheetMenu()
    const optionLabel = (option: { label: string; dotClassName?: string }): JSX.Element => (
        <span className="flex items-center gap-2">
            {option.dotClassName && (
                <span aria-hidden className={cn('size-2 shrink-0 rounded-full', option.dotClassName)} />
            )}
            {option.label}
        </span>
    )
    return (
        <TodayRecentFilterSubmenu
            label={label}
            value={options.find((option) => option.value === value)?.label ?? ''}
            narrowed={value !== defaultValue}
        >
            {sheet ? (
                options.map((option) => (
                    <ItemRadio
                        key={option.value}
                        aria-checked={option.value === value}
                        onClick={() => {
                            onChange(option.value)
                            sheet.back()
                        }}
                        data-attr={dataAttr}
                    >
                        {optionLabel(option)}
                    </ItemRadio>
                ))
            ) : (
                <DropdownMenuRadioGroup value={value} onValueChange={(next) => onChange(next as T)}>
                    {options.map((option) => (
                        <DropdownMenuRadioItem key={option.value} value={option.value} data-attr={dataAttr}>
                            {optionLabel(option)}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            )}
        </TodayRecentFilterSubmenu>
    )
}
