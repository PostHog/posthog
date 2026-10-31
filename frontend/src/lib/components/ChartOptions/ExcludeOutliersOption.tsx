import { ChartOptionSwitch } from './ChartOptionSwitch'

export interface ExcludeOutliersOptionProps {
    checked: boolean
    onChange: (checked: boolean) => void
}

export function ExcludeOutliersOption({ checked, onChange }: ExcludeOutliersOptionProps): JSX.Element {
    return (
        <ChartOptionSwitch
            label="Exclude outliers"
            info="When on, whiskers stop at 1.5 times the interquartile range, so differences between the quartiles are easier to see. When off, the Y-axis stretches to show every value."
            checked={checked}
            onChange={onChange}
        />
    )
}
