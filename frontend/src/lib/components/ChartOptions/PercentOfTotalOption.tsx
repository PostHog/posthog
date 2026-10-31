import { ChartOptionSwitch } from './ChartOptionSwitch'

export interface PercentOfTotalOptionProps {
    checked: boolean
    onChange: (checked: boolean) => void
}

export function PercentOfTotalOption({ checked, onChange }: PercentOfTotalOptionProps): JSX.Element {
    return <ChartOptionSwitch label="Show as % of total" checked={checked} onChange={onChange} />
}
