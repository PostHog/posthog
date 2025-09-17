import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { PreLaunchChecklist } from './PreLaunchChecklist'

export function ExperimentHeader(): JSX.Element {
    const { isExperimentRunning } = useValues(experimentLogic)

    return (
        <>
            {!isExperimentRunning && (
                <div className="w-1/2">
                    <PreLaunchChecklist />
                </div>
            )}
        </>
    )
}
