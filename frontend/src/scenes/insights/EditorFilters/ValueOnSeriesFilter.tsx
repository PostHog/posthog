import { useActions, useValues } from 'kea'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from '../insightLogic'
import { valueOnSeriesFilterLogic } from './valueOnSeriesFilterLogic'

export function ValueOnSeriesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { valueOnSeries } = useValues(valueOnSeriesFilterLogic(insightProps))
    const { setValueOnSeries } = useActions(valueOnSeriesFilterLogic(insightProps))

    return (
        <LemonCheckbox
            checked={valueOnSeries}
            onChange={setValueOnSeries}
            label={<span className="font-normal">Show values on series</span>}
            bordered
            size="small"
        />
    )
}
