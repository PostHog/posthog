import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from '@posthog/quill'

export interface QuillOption {
    value: string
    label: string
}

export interface QuillOptionComboboxProps {
    id?: string
    options: QuillOption[]
    value: string
    onChange: (value: string) => void
    placeholder: string
    emptyText: string
    loading?: boolean
    disabled?: boolean
    invalid?: boolean
    dataAttr?: string
}

export function QuillOptionCombobox({
    id,
    options,
    value,
    onChange,
    placeholder,
    emptyText,
    loading,
    disabled,
    invalid,
    dataAttr,
}: QuillOptionComboboxProps): JSX.Element {
    const labelByValue = new Map(options.map((option) => [option.value, option.label]))

    return (
        <Combobox
            items={options.map((option) => option.value)}
            value={value || null}
            onValueChange={(next: string | null) => {
                if (next) {
                    onChange(next)
                }
            }}
            itemToStringLabel={(optionValue: string) => labelByValue.get(optionValue) ?? optionValue}
            disabled={disabled}
        >
            <ComboboxInput
                id={id}
                placeholder={loading ? 'Loading...' : placeholder}
                aria-invalid={invalid || undefined}
                disabled={disabled}
                data-attr={dataAttr}
            />
            <ComboboxContent>
                <ComboboxEmpty>{loading ? 'Loading...' : emptyText}</ComboboxEmpty>
                <ComboboxList>
                    {(optionValue: string) => (
                        <ComboboxItem key={optionValue} value={optionValue}>
                            {labelByValue.get(optionValue) ?? optionValue}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
