import { useActions, useValues } from 'kea'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from '../insightLogic'
import { valueOnSeriesFilterLogic } from './valueOnSeriesFilterLogic'

type ValuesOnSeriesFilterProps = { onChange: (checked: boolean) => void; checked: boolean }

export function ValueOnSeriesFilterDataExploration(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { valueOnSeries } = useValues(valueOnSeriesFilterLogic(insightProps))
    const { setValueOnSeries } = useActions(valueOnSeriesFilterLogic(insightProps))
    return <ValueOnSeriesFilter checked={valueOnSeries} onChange={setValueOnSeries} />
}

// the component is used in the non data exploration case and wrapped by above component for data exploration
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
