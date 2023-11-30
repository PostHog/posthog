import './ChartSelection.scss'

import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const ChartSelection = (): JSX.Element => {
    const logic = useMountedLogic(dataVisualizationLogic)
    const { columns, responseLoading, selectedXIndex, selectedYIndex } = useValues(logic)
    const { setXAxis, setYAxis } = useActions(logic)

    const options = columns.map(({ name, type }) => ({
        value: name,
        label: `${name} - ${type}`,
    }))

    return (
        <div className="ChartSelectionWrapper">
            <div className="ChartSelection">
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
