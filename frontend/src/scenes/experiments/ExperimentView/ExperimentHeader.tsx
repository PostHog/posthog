import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import { Exposures } from './Exposures'
import { PreLaunchChecklist } from './PreLaunchChecklist'

function PreLaunchExperimentHeader(): JSX.Element {
    return (
        <>
            <PreLaunchChecklist />
        </>
    )
}

function LaunchedExperimentHeader(): JSX.Element {
    return (
        <>
            <Exposures />
        </>
    )
}

export function ExperimentHeader(): JSX.Element {
    const { isExperimentRunning } = useValues(experimentLogic)

    return (
        <>
            {isExperimentRunning ? <LaunchedExperimentHeader /> : <PreLaunchExperimentHeader />}
            <RunningTimeCalculatorModal />
        </>
    )
}
