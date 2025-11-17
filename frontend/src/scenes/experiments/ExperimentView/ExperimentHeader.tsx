import { useValues } from 'kea'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { WebExperimentImplementationDetails } from '../WebExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { PreLaunchChecklist } from './PreLaunchChecklist'

export function ExperimentHeader(): JSX.Element {
    const { experiment, isExperimentRunning } = useValues(experimentLogic)

    return (
        <>
            {!isExperimentRunning && (
                <>
                    <div className="w-1/2">
                        <PreLaunchChecklist />
                    </div>
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}
                </>
            )}
        </>
    )
}
