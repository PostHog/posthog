import { useActions, useValues } from 'kea'

import { VariantsPanelCreateFeatureFlag } from '../../ExperimentForm/VariantsPanelCreateFeatureFlag'
import { experimentWizardLogic } from '../experimentWizardLogic'

export function VariantsStep(): JSX.Element {
    const { experiment } = useValues(experimentWizardLogic)
    const { setFeatureFlagConfig } = useActions(experimentWizardLogic)

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold">Who sees what variant?</h3>
            </div>
            <VariantsPanelCreateFeatureFlag experiment={experiment} onChange={setFeatureFlagConfig} layout="vertical" />
        </div>
    )
}
