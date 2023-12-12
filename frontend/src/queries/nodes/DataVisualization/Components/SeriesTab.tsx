import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconDelete, IconPlusMini } from 'lib/lemon-ui/icons'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const SeriesTab = (): JSX.Element => {
    const { columns, xData, yData } = useValues(dataVisualizationLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { updateXSeries, updateYSeries, addYSeries, deleteYSeries } = useActions(dataVisualizationLogic)

    const options = columns.map(({ name, label }) => ({
        value: name,
        label,
    }))

    return (
        <div className="flex flex-col w-full">
            <LemonLabel>X-axis</LemonLabel>
            <LemonSelect
                className="w-full"
                value={xData !== null ? xData.column.label : 'None'}
                options={options}
                disabledReason={responseLoading ? 'Query loading...' : undefined}
                onChange={(value) => {
                    const column = columns.find((n) => n.name === value)
                    if (column) {
                        updateXSeries(column.name)
                    }
                }}
            />
            <LemonLabel className="mt-4">Y-axis</LemonLabel>
            {(yData ?? [null]).map((series, index) => (
                <div className="flex gap-1 mb-1" key={series?.column.name}>
                    <LemonSelect
                        className="grow"
                        value={series !== null ? series.column.label : 'None'}
                        options={options}
                        disabledReason={responseLoading ? 'Query loading...' : undefined}
                        onChange={(value) => {
                            const column = columns.find((n) => n.name === value)
                            if (column) {
                                updateYSeries(index, column.name)
                            }
                        }}
                    />
                    <LemonButton
                        key="delete"
                        icon={<IconDelete />}
                        status="primary-alt"
                        title="Delete Y-series"
                        noPadding
                        onClick={() => deleteYSeries(index)}
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
    )
}
