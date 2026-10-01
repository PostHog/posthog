import { useValues } from 'kea'

import { ExperimentImplementationDetails } from '../../ExperimentImplementationDetails'
import { experimentWizardLogic } from '../experimentWizardLogic'

/** Shown once the draft is saved, so the snippet uses the saved flag's key and variants */
export function ImplementationStep(): JSX.Element {
    const { experiment } = useValues(experimentWizardLogic)

    return (
        <div className="space-y-6">
            <div className="space-y-1">
                <h3 className="text-lg font-semibold">Add the experiment to your code</h3>
                <p className="text-secondary mb-0">
                    Your experiment is saved as a draft. Add this code where people see the change. Once it's deployed,
                    launch the experiment from its page.
                </p>
            </div>
            <ExperimentImplementationDetails experiment={experiment} showTitle={false} />
        </div>
    )
}
