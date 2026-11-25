import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    useComboboxAnchor,
} from '@posthog/quill'

export interface QuillScopeTargetOption {
    value: string
    label: string
    description?: string
}

export function QuillScopeTargetCombobox({
    id,
    options,
    value,
    onChange,
    placeholder,
    emptyText,
    dataAttr,
}: {
    id?: string
    options: QuillScopeTargetOption[]
    value: string[]
    onChange: (value: string[]) => void
    placeholder: string
    emptyText: string
    dataAttr: string
}): JSX.Element {
    const optionByValue = new Map(options.map((option) => [option.value, option]))

    return (
        <Combobox<string, true>
            multiple
            items={options.map((option) => option.value)}
            value={value}
            onValueChange={(next, eventDetails) => {
                // Escape with the list closed would otherwise clear every selection.
                if (eventDetails.reason === 'escape-key') {
                    eventDetails.allowPropagation()
                    return
                }
                onChange(next ?? [])
            }}
            itemToStringLabel={(optionValue: string) => optionByValue.get(optionValue)?.label ?? optionValue}
        >
            <QuillScopeTargetChips
                id={id}
                optionByValue={optionByValue}
                placeholder={placeholder}
                emptyText={emptyText}
                dataAttr={dataAttr}
            />
        </Combobox>
    )
}

function QuillScopeTargetChips({
    id,
    optionByValue,
    placeholder,
    emptyText,
    dataAttr,
}: {
    id?: string
    optionByValue: Map<string, QuillScopeTargetOption>
    placeholder: string
    emptyText: string
    dataAttr: string
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor} data-attr={dataAttr}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((selected) => (
                                <ComboboxChip key={selected}>
                                    {optionByValue.get(selected)?.label ?? selected}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput id={id} placeholder={values.length ? '' : placeholder} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>{emptyText}</ComboboxEmpty>
                <ComboboxList>
                    {(optionValue: string) => (
                        <ComboboxItem
                            key={optionValue}
                            value={optionValue}
                            description={optionByValue.get(optionValue)?.description}
                        >
                            {optionByValue.get(optionValue)?.label ?? optionValue}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
