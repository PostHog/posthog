import { useValues } from 'kea'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { WebExperimentImplementationDetails } from '../WebExperimentImplementationDetails'

export function ExperimentHeader(): JSX.Element {
    const { experiment, isExperimentLaunched } = useValues(experimentLogic)

    return (
        <>
            {!isExperimentLaunched && (
                <div className="border rounded bg-surface-primary p-4">
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}
                </div>
            )}
        </>
    )
}
