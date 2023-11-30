import './Chart.scss'

import { useMountedLogic, useValues } from 'kea'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { LineGraph } from './Charts/LineGraph'
import { ChartSelection } from './ChartSelection'

export const Chart = (): JSX.Element => {
    const logic = useMountedLogic(dataVisualizationLogic)
    const { showEditingUI } = useValues(logic)
    return (
        <div className="Chart__Container">
            {showEditingUI && (
                <div className="h-full">
                    <ChartSelection />
                </div>
            )}
            <div className="w-full">
                <LineGraph />
            </div>
        </div>
    )
}
