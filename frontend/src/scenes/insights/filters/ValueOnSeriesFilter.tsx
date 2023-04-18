import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'

export function ValueOnSeriesFilter(props: { onChange: (checked: boolean) => void; checked: boolean }): JSX.Element {
    return (
        <LemonCheckbox
            onChange={props.onChange}
            checked={props.checked}
            label={<span className="font-normal">Show values on series</span>}
            bordered
            size="small"
        />
    )
}
