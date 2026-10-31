import { ChartOptionSwitch } from './ChartOptionSwitch'

export interface ValuesOnSeriesOptionProps {
    checked: boolean
    onChange: (checked: boolean) => void
}

export function ValuesOnSeriesOption({ checked, onChange }: ValuesOnSeriesOptionProps): JSX.Element {
    return <ChartOptionSwitch label="Show values on series" checked={checked} onChange={onChange} />
}
