import './Chart.scss'

import { useValues } from 'kea'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { LineGraph } from './Charts/LineGraph'
import { ChartSelection } from './ChartSelection'

export const Chart = (): JSX.Element => {
    const { showEditingUI } = useValues(dataVisualizationLogic)

    return (
        <div className="flex flex-row gap-4">
            {showEditingUI && (
                <div className="h-full">
                    <ChartSelection />
                </div>
            )}
            <div className="w-full overflow-auto">
                <LineGraph />
            </div>
        </div>
    )
}
