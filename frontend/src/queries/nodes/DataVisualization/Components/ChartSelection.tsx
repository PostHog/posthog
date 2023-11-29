import './ChartSelection.scss'

import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { useMountedLogic, useValues } from 'kea'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const ChartSelection = (): JSX.Element => {
    const logic = useMountedLogic(dataVisualizationLogic)
    const { columns } = useValues(logic)

    const options = columns.map(({ name, type }) => ({
        value: name,
        label: `${name} - ${type}`,
    }))

    return (
        <div className="ChartSelectionWrapper">
            <div className="ChartSelection">
                <LemonLabel>X-axis</LemonLabel>
                <LemonSelect value={'None'} options={options} />
                <LemonLabel className="">Y-axis</LemonLabel>
                <LemonSelect value={'None'} options={options} />
            </div>
        </div>
    )
}
