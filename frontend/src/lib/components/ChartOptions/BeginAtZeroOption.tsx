import { ChartOptionSwitch } from './ChartOptionSwitch'

export interface BeginAtZeroOptionProps {
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string | null
    'data-attr'?: string
}

export function BeginAtZeroOption({
    checked,
    onChange,
    disabledReason,
    'data-attr': dataAttr,
}: BeginAtZeroOptionProps): JSX.Element {
    return (
        <ChartOptionSwitch
            label="Begin at zero"
            info="When off, the axis starts just below your lowest value instead of at zero, so small changes are easier to see."
            checked={checked}
            onChange={onChange}
            disabledReason={disabledReason}
            data-attr={dataAttr}
        />
    )
}
