import { useMemo } from 'react'

import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    useComboboxAnchor,
} from '@posthog/quill'

export interface QuillVariableOption {
    value: string
    label: string
}

export interface QuillVariableOptionsComboboxProps {
    id?: string
    multiple: boolean
    options: QuillVariableOption[]
    selectedValues: string[]
    onChange: (values: string[]) => void
    placeholder: string
    emptyState?: string
}

/** Picks one or many of a list variable's options, with each option's label shown in place of its value. */
export function QuillVariableOptionsCombobox({
    id,
    multiple,
    options,
    selectedValues,
    onChange,
    placeholder,
    emptyState = 'No matching options',
}: QuillVariableOptionsComboboxProps): JSX.Element {
    const labels = useMemo(() => new Map(options.map((option) => [option.value, option.label])), [options])
    // A saved default can be missing from the options a query returns, so keep it selectable and visible.
    const values = useMemo(
        () => Array.from(new Set([...options.map((option) => option.value), ...selectedValues])),
        [options, selectedValues]
    )
    const labelFor = (value: string): string => labels.get(value) ?? value

    if (multiple) {
        return (
            <Combobox<string, true>
                multiple
                items={values}
                value={selectedValues}
                onValueChange={(next) => onChange(next ?? [])}
                itemToStringLabel={labelFor}
            >
                <MultipleBody
                    id={id}
                    labelFor={labelFor}
                    placeholder={selectedValues.length === 0 ? placeholder : undefined}
                    emptyState={emptyState}
                />
            </Combobox>
        )
    }

    return (
        <Combobox<string>
            items={values}
            value={selectedValues[0] ?? null}
            onValueChange={(next) => onChange(next ? [next] : [])}
            itemToStringLabel={labelFor}
        >
            <ComboboxInput id={id} className="w-full" placeholder={placeholder} showClear />
            <OptionsList labelFor={labelFor} emptyState={emptyState} />
        </Combobox>
    )
}

function OptionsList({
    labelFor,
    emptyState,
    anchor,
}: {
    labelFor: (value: string) => string
    emptyState: string
    anchor?: React.RefObject<HTMLDivElement | null>
}): JSX.Element {
    return (
        <ComboboxContent anchor={anchor}>
            <ComboboxEmpty>{emptyState}</ComboboxEmpty>
            <ComboboxList>
                {(value: string) => (
                    <ComboboxItem key={value} value={value}>
                        {labelFor(value)}
                    </ComboboxItem>
                )}
            </ComboboxList>
        </ComboboxContent>
    )
}

/** The chips field reads its anchor from the surrounding `Combobox`, so it renders inside it. */
function MultipleBody({
    id,
    labelFor,
    placeholder,
    emptyState,
}: {
    id?: string
    labelFor: (value: string) => string
    placeholder?: string
    emptyState: string
}): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor} className="w-full">
                <ComboboxValue>
                    {(chosen) => (
                        <>
                            {(chosen as string[]).map((value) => (
                                <ComboboxChip key={value} title={labelFor(value)}>
                                    {labelFor(value)}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput id={id} placeholder={placeholder} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <OptionsList labelFor={labelFor} emptyState={emptyState} anchor={anchor} />
        </>
    )
}
