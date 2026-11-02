import { ChartOptionToggleGroup } from './ChartOptionToggleGroup'

export type AxisScale = 'linear' | 'log'

const SCALE_OPTIONS: { value: AxisScale; label: string }[] = [
    { value: 'linear', label: 'Linear' },
    { value: 'log', label: 'Logarithmic' },
]

export interface AxisScaleOptionProps {
    label?: string
    value: AxisScale
    onChange: (value: AxisScale) => void
}

export function AxisScaleOption({ label, value, onChange }: AxisScaleOptionProps): JSX.Element {
    return <ChartOptionToggleGroup label={label} value={value} options={SCALE_OPTIONS} onChange={onChange} />
}
