import { useValues } from 'kea'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { WebExperimentImplementationDetails } from '../WebExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'

export function ExperimentHeader(): JSX.Element {
    const { experiment, isExperimentRunning } = useValues(experimentLogic)

    return (
        <>
            {!isExperimentRunning && (
                <>
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
