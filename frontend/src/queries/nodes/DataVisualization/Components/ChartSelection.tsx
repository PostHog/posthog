import './ChartSelection.scss'

import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const ChartSelection = (): JSX.Element => {
    const { columns, selectedXIndex, selectedYIndex } = useValues(dataVisualizationLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { setXAxis, setYAxis } = useActions(dataVisualizationLogic)

    const options = columns.map(({ name, type }) => ({
        value: name,
        label: `${name} - ${type}`,
    }))

    return (
        <div className="ChartSelectionWrapper bg-bg-light border p-4">
            <div className="flex flex-col">
                <LemonLabel>X-axis</LemonLabel>
                <LemonSelect
                    value={selectedXIndex !== null ? options[selectedXIndex]?.label : 'None'}
                    options={options}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => {
                        const index = options.findIndex((n) => n.value === value)
                        setXAxis(index)
                    }}
                />
                <LemonLabel className="mt-4">Y-axis</LemonLabel>
                <LemonSelect
                    value={selectedYIndex !== null ? options[selectedYIndex]?.label : 'None'}
                    options={options}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => {
                        const index = options.findIndex((n) => n.value === value)
                        setYAxis(index)
                    }}
                />
            </div>
        </div>
    )
}
