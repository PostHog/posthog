import './Chart.scss'

import clsx from 'clsx'
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
            <div
                className={clsx('w-full h-full flex-1 overflow-auto', {
                    'pt-[46px]': showEditingUI,
                })}
            >
                <LineGraph />
            </div>
        </div>
    )
}
