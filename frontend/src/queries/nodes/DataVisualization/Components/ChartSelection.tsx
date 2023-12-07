import './ChartSelection.scss'

import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconDelete, IconPlusMini } from 'lib/lemon-ui/icons'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const ChartSelection = (): JSX.Element => {
    const { columns, selectedXIndex, selectedYIndexes } = useValues(dataVisualizationLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { updateXSeries, updateYSeries, addYSeries, deletedYSeries } = useActions(dataVisualizationLogic)

    const options = columns.map(({ name, type }) => ({
        value: name,
        label: `${name} - ${type}`,
    }))

    return (
        <div className="ChartSelectionWrapper bg-bg-light border p-4">
            <div className="flex flex-col">
                <LemonLabel>X-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={selectedXIndex !== null ? options[selectedXIndex]?.label : 'None'}
                    options={options}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => {
                        const columnIndex = options.findIndex((n) => n.value === value)
                        updateXSeries(columnIndex)
                    }}
                />
                <LemonLabel className="mt-4">Y-axis</LemonLabel>
                {(selectedYIndexes ?? [null]).map((selectedYIndex, index) => (
                    <div className="flex gap-1 mb-1" key={selectedYIndex}>
                        <LemonSelect
                            className="grow"
                            value={selectedYIndex !== null ? options[selectedYIndex]?.label : 'None'}
                            options={options}
                            disabledReason={responseLoading ? 'Query loading...' : undefined}
                            onChange={(value) => {
                                const columnIndex = options.findIndex((n) => n.value === value)
                                updateYSeries(index, columnIndex)
                            }}
                        />
                        <LemonButton
                            key="delete"
                            icon={<IconDelete />}
                            status="primary-alt"
                            title="Delete Y-series"
                            noPadding
                            onClick={() => deletedYSeries(index)}
                        />
                    </div>
                ))}
                <LemonButton
                    className="mt-1"
                    type="tertiary"
                    onClick={() => addYSeries()}
                    icon={<IconPlusMini />}
                    fullWidth
                >
                    Add Y-series
                </LemonButton>
            </div>
        </div>
    )
}
