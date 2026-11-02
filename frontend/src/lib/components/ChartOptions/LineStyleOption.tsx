import { ChartOptionToggleGroup } from './ChartOptionToggleGroup'

export type LineStyle = 'smooth' | 'linear'

const LINE_STYLE_OPTIONS: { value: LineStyle; label: string }[] = [
    { value: 'smooth', label: 'Smooth' },
    { value: 'linear', label: 'Straight' },
]

export interface LineStyleOptionProps {
    label?: string
    value: LineStyle
    onChange: (value: LineStyle) => void
    'data-attr'?: string
}

export function LineStyleOption({ label, value, onChange, 'data-attr': dataAttr }: LineStyleOptionProps): JSX.Element {
    return (
        <ChartOptionToggleGroup
            label={label}
            value={value}
            options={LINE_STYLE_OPTIONS}
            onChange={onChange}
            data-attr={dataAttr}
        />
    )
}
