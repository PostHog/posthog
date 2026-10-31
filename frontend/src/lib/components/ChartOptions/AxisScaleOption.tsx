import { ChartOptionToggleGroup } from './ChartOptionToggleGroup'

export type AxisScale = 'linear' | 'log'

const SCALE_OPTIONS: { value: AxisScale; label: string }[] = [
    { value: 'linear', label: 'Linear' },
    { value: 'log', label: 'Logarithmic' },
]

export interface AxisScaleOptionProps {
    value: AxisScale
    onChange: (value: AxisScale) => void
}

export function AxisScaleOption({ value, onChange }: AxisScaleOptionProps): JSX.Element {
    return <ChartOptionToggleGroup label="Scale" value={value} options={SCALE_OPTIONS} onChange={onChange} />
}
