import { NumberFieldGroup, NumberFieldInput, NumberFieldRoot } from '@posthog/quill'

export interface QuillCheckNumberInputProps {
    id: string
    value: number | null
    onChange: (value: number | null) => void
    invalid: boolean
    min: number
    placeholder?: string
    dataAttr?: string
}

export function QuillCheckNumberInput({
    id,
    value,
    onChange,
    invalid,
    min,
    placeholder,
    dataAttr,
}: QuillCheckNumberInputProps): JSX.Element {
    return (
        <NumberFieldRoot
            value={value !== null && Number.isFinite(value) ? value : null}
            onValueChange={(next: number | null) => onChange(next)}
            min={min}
            allowOutOfRange
        >
            <NumberFieldGroup>
                <NumberFieldInput
                    id={id}
                    placeholder={placeholder}
                    aria-invalid={invalid || undefined}
                    data-attr={dataAttr}
                />
            </NumberFieldGroup>
        </NumberFieldRoot>
    )
}
