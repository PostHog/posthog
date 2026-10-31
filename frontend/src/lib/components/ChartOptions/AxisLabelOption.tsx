import { ChartOptionTextInput } from './ChartOptionTextInput'

export interface AxisLabelOptionProps {
    value: string | undefined
    onChange: (value: string | undefined) => void
    placeholder?: string
    'data-attr'?: string
}

export function AxisLabelOption({
    value,
    onChange,
    placeholder,
    'data-attr': dataAttr,
}: AxisLabelOptionProps): JSX.Element {
    return (
        <ChartOptionTextInput
            label="Label"
            value={value}
            placeholder={placeholder ?? 'None'}
            onChange={onChange}
            data-attr={dataAttr}
        />
    )
}
