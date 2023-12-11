import './Chart.scss'

import { useValues } from 'kea'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { LineGraph } from './Charts/LineGraph'
import { SideBar } from './SideBar'

export const Chart = (): JSX.Element => {
    const { showEditingUI } = useValues(dataVisualizationLogic)

    return (
        <div className="flex flex-1 flex-row gap-4">
            {showEditingUI && (
                <div className="h-full">
                    <SideBar />
                </div>
            )}
            <div className="w-full flex flex-1 overflow-auto">
                <LineGraph />
            </div>
        </div>
    )
}
