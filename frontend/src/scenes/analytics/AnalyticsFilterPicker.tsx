import { ReactNode, useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Spinner,
    Text,
} from '@posthog/quill'

export interface AnalyticsFilterOption {
    value: string
    label: string
    media?: ReactNode
    /** A muted note after the label, such as "(you)". */
    hint?: string
}

interface AnalyticsFilterPickerProps {
    label: string
    value: string[]
    onChange: (value: string[]) => void
    options: AnalyticsFilterOption[]
    loading?: boolean
    onOpen?: () => void
    searchPlaceholder: string
    emptyText: string
    dataAttr: string
}

/** A filter that is a dropdown and a search at once: a button opens a searchable list to tick values in. */
export function AnalyticsFilterPicker({
    label,
    value,
    onChange,
    options,
    loading,
    onOpen,
    searchPlaceholder,
    emptyText,
    dataAttr,
}: AnalyticsFilterPickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)
    // The trigger opens the popup itself, so the list loads from here as well as from the combobox's own opens.
    const toggle = (next: boolean): void => {
        setOpen(next)
        if (next) {
            onOpen?.()
        }
    }
    const selected = options.filter((option) => value.includes(option.value))
    // Values the options do not know yet (a tag from the URL before the list loads) still count as picked.
    const unknown = value.filter((item) => !options.some((option) => option.value === item))
    const picked = [...selected, ...unknown.map((item) => ({ value: item, label: item }))]
    return (
        <Combobox
            multiple
            items={[...options, ...unknown.map((item) => ({ value: item, label: item }))]}
            itemToStringValue={(option: AnalyticsFilterOption) => option.label}
            isItemEqualToValue={(option: AnalyticsFilterOption, other: AnalyticsFilterOption) =>
                option.value === other.value
            }
            value={picked}
            onValueChange={(next: AnalyticsFilterOption[]) => onChange(next.map((option) => option.value))}
            open={open}
            onOpenChange={toggle}
        >
            <Button
                ref={triggerRef}
                variant="outline"
                size="sm"
                className="h-8"
                aria-haspopup="listbox"
                aria-expanded={open}
                onClick={() => toggle(!open)}
                data-attr={dataAttr}
            >
                {label}
                {value.length > 0 && (
                    <Text size="xs" variant="muted" render={<span />}>
                        {value.length}
                    </Text>
                )}
            </Button>
            <ComboboxContent anchor={triggerRef} className="min-w-64">
                <ComboboxInput placeholder={searchPlaceholder} showTrigger={false} />
                {value.length > 0 && (
                    <div className="px-1 pt-1">
                        <Button
                            variant="link-muted"
                            size="xs"
                            onClick={() => onChange([])}
                            data-attr={`${dataAttr}-clear`}
                        >
                            Clear selection
                        </Button>
                    </div>
                )}
                <ComboboxEmpty>
                    {loading ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Loading…
                        </span>
                    ) : (
                        emptyText
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(option: AnalyticsFilterOption) => (
                        <ComboboxItem key={option.value} value={option} title={option.label}>
                            {option.media}
                            <span className="truncate">{option.label}</span>
                            {option.hint && (
                                <Text size="xs" variant="muted" render={<span />} className="ml-auto">
                                    {option.hint}
                                </Text>
                            )}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
