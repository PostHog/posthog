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

export interface QuillApprovalPolicyOption {
    key: string
    label: string
}

export function QuillApprovalPolicyMultiSelect({
    id,
    options,
    value,
    placeholder,
    onChange,
}: {
    id: string
    options: QuillApprovalPolicyOption[]
    value: string[]
    placeholder: string
    onChange: (value: string[]) => void
}): JSX.Element {
    const labelsByKey = Object.fromEntries(options.map((option) => [option.key, option.label]))

    return (
        <Combobox<string, true>
            multiple
            autoHighlight
            items={options.map((option) => option.key)}
            itemToStringLabel={(key: string) => labelsByKey[key] ?? key}
            value={value}
            onValueChange={(next: string[]) => onChange(next ?? [])}
        >
            <OptionChips id={id} placeholder={placeholder} labelsByKey={labelsByKey} />
        </Combobox>
    )
}

function OptionChips({
    id,
    placeholder,
    labelsByKey,
}: {
    id: string
    placeholder: string
    labelsByKey: Record<string, string>
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((key) => (
                                <ComboboxChip key={key} title={labelsByKey[key] ?? key}>
                                    <span className="ph-no-capture">{labelsByKey[key] ?? key}</span>
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput id={id} placeholder={values.length ? '' : placeholder} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matches</ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => (
                        <ComboboxItem key={key} value={key}>
                            <span className="ph-no-capture">{labelsByKey[key] ?? key}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
