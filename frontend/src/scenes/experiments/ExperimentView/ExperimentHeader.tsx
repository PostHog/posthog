import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { Exposures } from './Exposures'
import { PreLaunchChecklist } from './PreLaunchChecklist'
import { RunningTime } from './RunningTime'

export function ExperimentHeader(): JSX.Element {
    const { isExperimentRunning } = useValues(experimentLogic)

    return (
        <>
            {!isExperimentRunning && (
                <div className="w-1/2">
                    <PreLaunchChecklist />
                </div>
            )}
            <div className="flex w-full space-x-4">
                <div className="w-1/4">
                    <RunningTime />
                </div>
                <div className="w-3/4">
                    <Exposures />
                </div>
            </div>
        </>
    )
}
