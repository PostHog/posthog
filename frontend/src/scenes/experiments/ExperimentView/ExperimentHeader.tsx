import { useValues } from 'kea'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { WebExperimentImplementationDetails } from '../WebExperimentImplementationDetails'

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
