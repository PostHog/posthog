import { ChartOptionSwitch } from './ChartOptionSwitch'

export interface PieTotalOptionProps {
    isDonut: boolean
    checked: boolean
    onChange: (checked: boolean) => void
}

export function PieTotalOption({ isDonut, checked, onChange }: PieTotalOptionProps): JSX.Element {
    return (
        <ChartOptionSwitch
            label={isDonut ? 'Show total in center' : 'Show total below chart'}
            checked={checked}
            onChange={onChange}
        />
    )
}
