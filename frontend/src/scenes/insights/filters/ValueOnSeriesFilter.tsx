import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'

type ValuesOnSeriesFilterProps = { onChange: (checked: boolean) => void; checked: boolean }

export function ValueOnSeriesFilter({ checked, onChange }: ValuesOnSeriesFilterProps): JSX.Element {
    return (
        <LemonCheckbox
            onChange={onChange}
            checked={checked}
            label={<span className="font-normal">Show values on series</span>}
            bordered
            size="small"
        />
    )
}
